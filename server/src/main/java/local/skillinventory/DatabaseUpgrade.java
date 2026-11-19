package local.skillinventory;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashSet;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@DependsOnDatabaseInitialization
class DatabaseUpgrade implements InitializingBean {
    private record Skill(long id, String oldName, SkillPackage.Metadata metadata) {}
    private record Release(long skillId, String version, SkillPackage.Metadata metadata) {}

    private final JdbcTemplate db;

    DatabaseUpgrade(JdbcTemplate db) {
        this.db = db;
    }

    @Override
    public void afterPropertiesSet() {
        db.execute((ConnectionCallback<Void>) connection -> {
            try (var sql = connection.createStatement()) {
                sql.execute("PRAGMA foreign_keys=OFF");
                connection.setAutoCommit(false);
                try {
                    if (hasColumn(connection, "skill", "slug")) migrateSkills(connection);
                    if (!hasColumn(connection, "account", "enabled")) {
                        sql.execute("ALTER TABLE account ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1");
                        sql.execute("ALTER TABLE account ADD COLUMN auth_revision INTEGER NOT NULL DEFAULT 0");
                    }
                    sql.execute("DROP TABLE IF EXISTS device_token");
                    sql.execute("""
                            CREATE TABLE IF NOT EXISTS client_session (
                              secret_hash TEXT PRIMARY KEY,
                              account_id INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE
                            )
                            """);
                    try (var violations = sql.executeQuery("PRAGMA foreign_key_check")) {
                        if (violations.next()) throw new IllegalStateException("迁移后的数据库外键校验失败");
                    }
                    connection.commit();
                } catch (SQLException | RuntimeException error) {
                    connection.rollback();
                    throw error;
                } finally {
                    connection.setAutoCommit(true);
                    sql.execute("PRAGMA foreign_keys=ON");
                }
            }
            return null;
        });
    }

    private static boolean hasColumn(Connection connection, String table, String column) throws SQLException {
        try (var sql = connection.createStatement(); var rows = sql.executeQuery("PRAGMA table_info(" + table + ")")) {
            while (rows.next()) if (column.equals(rows.getString("name"))) return true;
            return false;
        }
    }

    private static void migrateSkills(Connection connection) throws SQLException {
        var skills = new ArrayList<Skill>();
        var releases = new ArrayList<Release>();
        var names = new HashSet<String>();
        try (var sql = connection.createStatement();
             var rows = sql.executeQuery("SELECT id,slug,draft FROM skill ORDER BY id")) {
            while (rows.next()) {
                var oldName = rows.getString("slug");
                var metadata = metadata(rows.getBytes("draft"), oldName + " 草稿");
                if (!names.add(metadata.name())) {
                    throw new IllegalStateException("旧库中存在重复 Skill 名称：" + metadata.name());
                }
                skills.add(new Skill(rows.getLong("id"), oldName, metadata));
            }
        }
        try (var query = connection.prepareStatement("SELECT version,archive FROM release WHERE skill_id=?")) {
            for (var skill : skills) {
                query.setLong(1, skill.id());
                try (var rows = query.executeQuery()) {
                    while (rows.next()) {
                        var version = rows.getString("version");
                        var label = skill.oldName() + " " + version;
                        var metadata = metadata(rows.getBytes("archive"), label);
                        if (!skill.metadata().name().equals(metadata.name())) {
                            throw new IllegalStateException("旧库中草稿和发布版本的 Skill 名称不一致：" + label);
                        }
                        releases.add(new Release(skill.id(), version, metadata));
                    }
                }
            }
        }
        // 保留主键及原始 ZIP 字节，使授权、版本和归档状态随事务迁移。
        try (var sql = connection.createStatement()) {
            sql.execute("""
                    CREATE TABLE skill_migrated (
                      id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL, draft BLOB NOT NULL,
                      revision INTEGER NOT NULL DEFAULT 1, published_revision INTEGER, archived INTEGER NOT NULL DEFAULT 0
                    )
                    """);
            try (var insert = connection.prepareStatement("""
                    INSERT INTO skill_migrated(id,name,description,draft,revision,published_revision,archived)
                    SELECT id,?,?,draft,revision,published_revision,archived FROM skill WHERE id=?
                    """)) {
                for (var skill : skills) {
                    insert.setString(1, skill.metadata().name());
                    insert.setString(2, skill.metadata().description());
                    insert.setLong(3, skill.id());
                    insert.executeUpdate();
                }
            }
            sql.execute("DROP TABLE skill");
            sql.execute("ALTER TABLE skill_migrated RENAME TO skill");
        }
        try (var update = connection.prepareStatement("UPDATE release SET name=?,description=? WHERE skill_id=? AND version=?")) {
            for (var release : releases) {
                update.setString(1, release.metadata().name());
                update.setString(2, release.metadata().description());
                update.setLong(3, release.skillId());
                update.setString(4, release.version());
                update.executeUpdate();
            }
        }
    }

    private static SkillPackage.Metadata metadata(byte[] archive, String label) {
        try {
            return SkillPackage.read(archive).metadata();
        } catch (ApiError error) {
            throw new IllegalStateException("旧库 Skill 元数据无法迁移：" + label + "，" + error.getMessage(), error);
        }
    }
}
