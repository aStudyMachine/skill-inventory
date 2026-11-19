package local.skillinventory;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class Inventory {
    record DraftInput(String source) {}
    record Publication(String version) {}
    record Summary(String name, String description, String status) {}
    record Draft(Summary skill, String source, List<String> files, List<Long> roles,
                 List<Map<String, Object>> releases, String nextVersion) {}
    record Published(String name, String description, String version, String releasedAt,
                     List<String> files, String source, byte[] archive) {
        Map<String, Object> metadata() {
            return Map.of("name", name, "description", description,
                    "version", version, "releasedAt", releasedAt, "files", files);
        }
    }
    private record Skill(long id, Summary summary, byte[] draft, long revision) {}
    private record Version(long major, long minor, long patch) {
        static Version parse(String input) {
            if (input == null || !input.matches("(0|[1-9][0-9]{0,8})(\\.(0|[1-9][0-9]{0,8})){2}")) {
                throw ApiError.invalid("版本号须为主.次.修订，每段 1 至 9 位数字且无前导零");
            }
            var parts = Arrays.stream(input.split("\\.")).mapToLong(Long::parseLong).toArray();
            return new Version(parts[0], parts[1], parts[2]);
        }

        String next() {
            if (patch < 999_999_999) return major + "." + minor + "." + (patch + 1);
            if (minor < 999_999_999) return major + "." + (minor + 1) + ".0";
            return major < 999_999_999 ? (major + 1) + ".0.0" : "";
        }
    }

    private static final String STATUS = """
            CASE WHEN archived=1 THEN 'archived'
                 WHEN published_revision IS NULL THEN 'draft'
                 WHEN published_revision<>revision THEN 'modified'
                 ELSE 'published' END AS status
            """;
    private static final String ALLOWED = """
            s.archived=0 AND EXISTS (SELECT 1 FROM release WHERE skill_id=s.id) AND
              (?=1 OR EXISTS (
                SELECT 1 FROM skill_role sr JOIN account_role ar ON ar.role_id=sr.role_id
                  WHERE sr.skill_id=s.id AND ar.account_id=?
              ))
            """;
    private static final String RELEASE_ORDER = " ORDER BY major DESC,minor DESC,patch DESC";
    private final JdbcTemplate db;
    private final Accounts accounts;

    Inventory(JdbcTemplate db, Accounts accounts) {
        this.db = db;
        this.accounts = accounts;
    }

    List<Summary> adminList(String query) {
        return db.query("SELECT name,description," + STATUS + " FROM skill "
                        + "WHERE instr(lower(name), lower(?))>0 ORDER BY name",
                (row, index) -> new Summary(row.getString(1), row.getString(2), row.getString(3)), query);
    }

    Draft draft(String name) {
        var skill = skill(name);
        var pack = SkillPackage.read(skill.draft());
        var releases = releases(skill.id());
        var roles = db.queryForList("SELECT role_id FROM skill_role WHERE skill_id=? ORDER BY role_id",
                Long.class, skill.id());
        var next = releases.isEmpty() ? "1.0.0" : Version.parse((String) releases.getFirst().get("version")).next();
        return new Draft(skill.summary(), pack.source(), pack.names(), roles, releases, next);
    }

    @Transactional
    public SkillPackage.Metadata create(DraftInput input) {
        var pack = SkillPackage.text(source(input.source()));
        var metadata = pack.metadata();
        if (db.update("INSERT INTO skill(name,description,draft) VALUES(?,?,?) ON CONFLICT(name) DO NOTHING",
                metadata.name(), metadata.description(), pack.zip()) == 0) {
            throw ApiError.conflict("Skill 名称已存在");
        }
        return metadata;
    }

    @Transactional
    public SkillPackage.Metadata edit(String name, DraftInput input) {
        var skill = activeSkill(name);
        return saveDraft(skill, SkillPackage.read(skill.draft()).edit(source(input.source())));
    }

    @Transactional
    public SkillPackage.Metadata replace(String name, byte[] archive) {
        return saveDraft(activeSkill(name), SkillPackage.read(archive));
    }

    private SkillPackage.Metadata saveDraft(Skill skill, SkillPackage pack) {
        var metadata = pack.metadata();
        if (!skill.summary().name().equals(metadata.name()) && !"draft".equals(skill.summary().status())) {
            throw ApiError.conflict("首次发布后不能修改 Skill 名称");
        }
        if (db.update("UPDATE OR IGNORE skill SET name=?,description=?,draft=?,revision=revision+1 WHERE id=?",
                metadata.name(), metadata.description(), pack.zip(), skill.id()) == 0) {
            throw ApiError.conflict("Skill 名称已存在");
        }
        return metadata;
    }

    @Transactional
    public void publish(String name, String version) {
        var parsed = Version.parse(version);
        var skill = activeSkill(name);
        SkillPackage.read(skill.draft()).metadata();
        if (db.update("""
                INSERT INTO release(skill_id,version,major,minor,patch,name,description,archive,released_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(skill_id,version) DO NOTHING
                """, skill.id(), version, parsed.major(), parsed.minor(), parsed.patch(),
                skill.summary().name(), skill.summary().description(), skill.draft(), Instant.now().toString()) == 0) {
            throw ApiError.conflict("该版本已发布");
        }
        db.update("UPDATE skill SET published_revision=revision WHERE id=?", skill.id());
    }

    @Transactional
    public void delete(String name) {
        var skill = skill(name);
        if ("draft".equals(skill.summary().status())) db.update("DELETE FROM skill WHERE id=?", skill.id());
        else db.update("UPDATE skill SET archived=1 WHERE id=?", skill.id());
    }

    @Transactional
    public void grant(String name, List<Long> roles) {
        var skill = activeSkill(name);
        accounts.validateRoles(roles);
        db.update("DELETE FROM skill_role WHERE skill_id=?", skill.id());
        for (var role : roles.stream().distinct().toList()) {
            db.update("INSERT INTO skill_role(skill_id,role_id) VALUES(?,?)", skill.id(), role);
        }
    }

    List<Map<String, Object>> available(Accounts.Actor actor) {
        return db.queryForList("""
                SELECT r.name,r.description,r.version,r.released_at AS releasedAt
                FROM skill s JOIN release r ON r.skill_id=s.id AND r.version=(
                    SELECT version FROM release WHERE skill_id=s.id
                    ORDER BY major DESC,minor DESC,patch DESC LIMIT 1)
                WHERE
                """ + ALLOWED + " ORDER BY s.name", actor.admin(), actor.id());
    }

    List<Map<String, Object>> versions(Accounts.Actor actor, String name) {
        return releases(availableId(actor, name));
    }

    Published published(Accounts.Actor actor, String name, String version) {
        return release(availableId(actor, name), version);
    }

    Published history(String name, String version) {
        return release(skill(name).id(), version);
    }

    private long availableId(Accounts.Actor actor, String name) {
        var rows = db.queryForList("SELECT s.id FROM skill s WHERE s.name=? AND " + ALLOWED,
                Long.class, name, actor.admin(), actor.id());
        if (rows.isEmpty()) throw new ApiError(404, "skill_unavailable", "Skill 未发布、已归档或无读取权限");
        return rows.getFirst();
    }

    private List<Map<String, Object>> releases(long skill) {
        return db.queryForList("SELECT version,name,description,released_at AS releasedAt "
                + "FROM release WHERE skill_id=?" + RELEASE_ORDER, skill);
    }

    private Published release(long id, String version) {
        var sql = "SELECT version,name,description,archive,released_at FROM release WHERE skill_id=?";
        var args = new Object[]{id};
        if (version != null) {
            Version.parse(version);
            sql += " AND version=?";
            args = new Object[]{id, version};
        }
        var matches = db.query(sql + RELEASE_ORDER + " LIMIT 1", (row, index) -> {
            var bytes = row.getBytes("archive");
            var pack = SkillPackage.read(bytes);
            return new Published(row.getString("name"), row.getString("description"),
                    row.getString("version"), row.getString("released_at"), pack.names(), pack.source(), bytes);
        }, args);
        if (matches.isEmpty()) throw new ApiError(404, "version_unavailable", "发布版本不存在");
        return matches.getFirst();
    }

    private Skill skill(String name) {
        var rows = db.query("SELECT id,name,description,draft,revision," + STATUS + " FROM skill WHERE name=?",
                (row, index) -> new Skill(row.getLong("id"),
                        new Summary(row.getString("name"), row.getString("description"),
                                row.getString("status")), row.getBytes("draft"), row.getLong("revision")), name);
        if (rows.isEmpty()) throw ApiError.missing("Skill 不存在");
        return rows.getFirst();
    }

    private Skill activeSkill(String name) {
        var found = skill(name);
        if ("archived".equals(found.summary().status())) throw ApiError.conflict("Skill 已归档");
        return found;
    }

    private static String source(String source) {
        if (source == null || source.length() > 1024 * 1024) throw ApiError.invalid("正文最多 1 Mi 个字符");
        return source;
    }
}
