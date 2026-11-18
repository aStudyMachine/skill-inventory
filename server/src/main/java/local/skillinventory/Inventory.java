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
    record DraftInput(String slug, String name, String description, String source) {}
    record Publication(String version) {}
    record Summary(String slug, String name, String description, String status) {}
    record Draft(Summary skill, String source, List<String> files, List<Long> roles,
                 List<Map<String, Object>> releases, String nextVersion) {}
    record Published(String slug, String name, String description, String version, String releasedAt,
                     List<String> files, String source, byte[] archive) {
        Map<String, Object> metadata() {
            return Map.of("slug", slug, "name", name, "description", description,
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
        return db.query("SELECT slug,name,description," + STATUS + " FROM skill "
                        + "WHERE instr(lower(slug), lower(?))>0 OR instr(lower(name), lower(?))>0 ORDER BY slug",
                (row, index) -> new Summary(row.getString(1), row.getString(2), row.getString(3), row.getString(4)),
                query, query);
    }

    Draft draft(String slug) {
        var skill = skill(slug);
        var pack = SkillPackage.read(skill.draft());
        var releases = releases(skill.id());
        var roles = db.queryForList("SELECT role_id FROM skill_role WHERE skill_id=? ORDER BY role_id",
                Long.class, skill.id());
        var next = releases.isEmpty() ? "1.0.0" : Version.parse((String) releases.getFirst().get("version")).next();
        return new Draft(skill.summary(), pack.source(), pack.names(), roles, releases, next);
    }

    @Transactional
    public void create(DraftInput input) {
        checkSlug(input.slug());
        var pack = SkillPackage.text("").edit(source(input.source()));
        var name = Accounts.requiredText(input.name(), 128, "显示名称");
        if (db.update("INSERT INTO skill(slug,name,description,draft) VALUES(?,?,?,?) ON CONFLICT(slug) DO NOTHING",
                input.slug(), name, description(input.description()), pack.zip()) == 0) {
            throw ApiError.conflict("slug 已存在");
        }
    }

    @Transactional
    public void edit(String slug, DraftInput input) {
        var skill = activeSkill(slug);
        var pack = SkillPackage.read(skill.draft()).edit(source(input.source()));
        db.update("UPDATE skill SET name=?,description=?,draft=?,revision=revision+1 WHERE id=?",
                Accounts.requiredText(input.name(), 128, "显示名称"), description(input.description()),
                pack.zip(), skill.id());
    }

    @Transactional
    public void replace(String slug, byte[] archive) {
        var skill = activeSkill(slug);
        var pack = SkillPackage.read(archive);
        pack.validate();
        db.update("UPDATE skill SET draft=?,revision=revision+1 WHERE id=?", pack.zip(), skill.id());
    }

    @Transactional
    public void publish(String slug, String version) {
        var parsed = Version.parse(version);
        var skill = activeSkill(slug);
        SkillPackage.read(skill.draft()).validate();
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
    public void delete(String slug) {
        var skill = skill(slug);
        if ("draft".equals(skill.summary().status())) db.update("DELETE FROM skill WHERE id=?", skill.id());
        else db.update("UPDATE skill SET archived=1 WHERE id=?", skill.id());
    }

    @Transactional
    public void grant(String slug, List<Long> roles) {
        var skill = activeSkill(slug);
        accounts.validateRoles(roles);
        db.update("DELETE FROM skill_role WHERE skill_id=?", skill.id());
        for (var role : roles.stream().distinct().toList()) {
            db.update("INSERT INTO skill_role(skill_id,role_id) VALUES(?,?)", skill.id(), role);
        }
    }

    List<Map<String, Object>> available(Accounts.Actor actor) {
        return db.queryForList("""
                SELECT s.slug,r.name,r.description,r.version,r.released_at AS releasedAt
                FROM skill s JOIN release r ON r.skill_id=s.id AND r.version=(
                    SELECT version FROM release WHERE skill_id=s.id
                    ORDER BY major DESC,minor DESC,patch DESC LIMIT 1)
                WHERE
                """ + ALLOWED + " ORDER BY s.slug", actor.admin(), actor.id());
    }

    List<Map<String, Object>> versions(Accounts.Actor actor, String slug) {
        return releases(availableId(actor, slug));
    }

    Published published(Accounts.Actor actor, String slug, String version) {
        return release(availableId(actor, slug), slug, version);
    }

    Published history(String slug, String version) {
        return release(skill(slug).id(), slug, version);
    }

    private long availableId(Accounts.Actor actor, String slug) {
        var rows = db.queryForList("SELECT s.id FROM skill s WHERE s.slug=? AND " + ALLOWED,
                Long.class, slug, actor.admin(), actor.id());
        if (rows.isEmpty()) throw new ApiError(404, "skill_unavailable", "Skill 未发布、已归档或无读取权限");
        return rows.getFirst();
    }

    private List<Map<String, Object>> releases(long skill) {
        return db.queryForList("SELECT version,name,description,released_at AS releasedAt "
                + "FROM release WHERE skill_id=?" + RELEASE_ORDER, skill);
    }

    private Published release(long id, String slug, String version) {
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
            return new Published(slug, row.getString("name"), row.getString("description"),
                    row.getString("version"), row.getString("released_at"), pack.names(), pack.source(), bytes);
        }, args);
        if (matches.isEmpty()) throw new ApiError(404, "version_unavailable", "发布版本不存在");
        return matches.getFirst();
    }

    private Skill skill(String slug) {
        var rows = db.query("SELECT id,slug,name,description,draft,revision," + STATUS + " FROM skill WHERE slug=?",
                (row, index) -> new Skill(row.getLong("id"),
                        new Summary(row.getString("slug"), row.getString("name"), row.getString("description"),
                                row.getString("status")), row.getBytes("draft"), row.getLong("revision")), slug);
        if (rows.isEmpty()) throw ApiError.missing("Skill 不存在");
        return rows.getFirst();
    }

    private Skill activeSkill(String slug) {
        var found = skill(slug);
        if ("archived".equals(found.summary().status())) throw ApiError.conflict("Skill 已归档");
        return found;
    }

    private static void checkSlug(String slug) {
        if (slug == null || slug.length() > 64 || !slug.matches("[a-z0-9]+(?:-[a-z0-9]+)*")
                || slug.matches("(con|prn|aux|nul|com[0-9]|lpt[0-9])")) {
            throw ApiError.invalid("slug 须使用小写字母、数字和连字符，最多 64 个字符");
        }
    }

    private static String description(String text) {
        if (text == null || text.length() > 1024) throw ApiError.invalid("描述最多 1024 个字符");
        return text;
    }

    private static String source(String source) {
        if (source == null || source.length() > 1024 * 1024) throw ApiError.invalid("正文最多 1 Mi 个字符");
        return source;
    }
}
