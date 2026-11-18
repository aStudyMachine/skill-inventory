package local.skillinventory;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class Accounts {
    record Actor(long id, String username, boolean admin) {}
    record Credentials(String username, String password) {}
    record Ids(List<Long> ids) {}
    record Name(String name) {}

    private static final String SESSION_ACTOR = "inventory-account-id";
    private final JdbcTemplate db;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final SecureRandom random = new SecureRandom();

    Accounts(JdbcTemplate db) {
        this.db = db;
    }

    @Bean
    ApplicationRunner initializeAdmin() {
        return args -> {
            if (db.queryForObject("SELECT count(*) FROM account WHERE admin=1", Integer.class) == 0) {
                var password = adminPassword;
                if (password == null || password.isEmpty()) {
                    throw new IllegalStateException("首次启动请运行 start.ps1 -InitializeAdmin 或设置 INVENTORY_ADMIN_PASSWORD");
                }
                create(new Credentials("admin", password), true);
            }
        };
    }

    @org.springframework.beans.factory.annotation.Value("${inventory.admin-password:}")
    private String adminPassword;

    Actor signIn(HttpServletRequest request, Credentials input) {
        var rows = db.query("SELECT id,username,admin,password_hash FROM account WHERE username=?",
                (row, index) -> Map.entry(new Actor(row.getLong(1), row.getString(2), row.getBoolean(3)),
                        row.getString(4)), input.username());
        if (rows.isEmpty() || !validPasswordSize(input.password())
                || !encoder.matches(input.password(), rows.getFirst().getValue())) {
            throw new ApiError(401, "invalid_credentials", "账号或密码错误");
        }
        var previous = request.getSession(false);
        if (previous != null) previous.invalidate();
        var actor = rows.getFirst().getKey();
        request.getSession().setAttribute(SESSION_ACTOR, actor.id());
        return actor;
    }

    Actor browser(HttpServletRequest request) {
        var session = request.getSession(false);
        if (session != null && session.getAttribute(SESSION_ACTOR) instanceof Long id) {
            var found = actors("SELECT id,username,admin FROM account WHERE id=?", id);
            if (!found.isEmpty()) return found.getFirst();
        }
        throw new ApiError(401, "login_required", "请先登录");
    }

    Actor consumer(HttpServletRequest request) {
        var header = request.getHeader("Authorization");
        if (header == null) return browser(request);
        if (header.startsWith("Bearer ") && header.substring(7).matches("[a-zA-Z0-9_-]{43}")) {
            var found = actors("""
                    SELECT a.id,a.username,a.admin FROM device_token t JOIN account a
                      ON a.id=t.account_id WHERE t.secret_hash=?
                    """, hash(header.substring(7)));
            if (!found.isEmpty()) return found.getFirst();
        }
        throw new ApiError(401, "invalid_token", "设备令牌无效或已撤销");
    }

    void administrator(HttpServletRequest request) {
        if (!browser(request).admin()) throw new ApiError(403, "admin_required", "需要管理员权限");
    }

    private List<Actor> actors(String sql, Object argument) {
        return db.query(sql, (row, index) -> new Actor(row.getLong(1), row.getString(2), row.getBoolean(3)), argument);
    }

    void create(Credentials input, boolean admin) {
        if (input.username() == null || !input.username().matches("[a-zA-Z0-9_.-]{1,64}")) {
            throw ApiError.invalid("账号由 1 至 64 位字母、数字、点、下划线或连字符组成");
        }
        if (!validPasswordSize(input.password()) || input.password().length() < 10) {
            throw ApiError.invalid("密码至少 10 个字符，且 UTF-8 编码不超过 72 字节");
        }
        if (db.update("INSERT INTO account(username,password_hash,admin) VALUES(?,?,?) ON CONFLICT(username) DO NOTHING",
                input.username(), encoder.encode(input.password()), admin) == 0) {
            throw ApiError.conflict("账号已存在");
        }
    }

    private static boolean validPasswordSize(String password) {
        return password != null && password.getBytes(StandardCharsets.UTF_8).length <= 72;
    }

    List<Map<String, Object>> listAccounts() {
        return db.query("SELECT id,username,admin FROM account ORDER BY username",
                (row, index) -> new Actor(row.getLong(1), row.getString(2), row.getBoolean(3)))
                .stream().<Map<String, Object>>map(actor -> Map.of("id", actor.id(),
                        "username", actor.username(), "admin", actor.admin(), "roles", rolesFor(actor.id())))
                .toList();
    }

    List<Map<String, Object>> listRoles() {
        return db.queryForList("SELECT id,name FROM role ORDER BY name");
    }

    void createRole(String name) {
        if (db.update("INSERT INTO role(name) VALUES(?) ON CONFLICT(name) DO NOTHING", requiredText(name, 64, "角色名称")) == 0) {
            throw ApiError.conflict("角色已存在");
        }
    }

    @Transactional
    public void assignRoles(long account, List<Long> roles) {
        if (actors("SELECT id,username,admin FROM account WHERE id=?", account).isEmpty()) {
            throw ApiError.missing("账号不存在");
        }
        validateRoles(roles);
        db.update("DELETE FROM account_role WHERE account_id=?", account);
        for (var role : roles.stream().distinct().toList()) {
            db.update("INSERT INTO account_role(account_id,role_id) VALUES(?,?)", account, role);
        }
    }

    private List<Long> rolesFor(long account) {
        return db.queryForList("SELECT role_id FROM account_role WHERE account_id=? ORDER BY role_id", Long.class, account);
    }

    void validateRoles(List<Long> roles) {
        if (roles == null || roles.size() > 512 || roles.stream().anyMatch(java.util.Objects::isNull)) {
            throw ApiError.invalid("角色列表无效");
        }
        var existing = db.queryForList("SELECT id FROM role", Long.class);
        if (!existing.containsAll(roles)) throw ApiError.invalid("角色不存在");
    }

    List<Map<String, Object>> tokens(Actor actor) {
        return db.queryForList("SELECT id,name,created_at AS createdAt FROM device_token WHERE account_id=? ORDER BY created_at",
                actor.id());
    }

    Map<String, String> issueToken(Actor actor, String name) {
        name = requiredText(name, 80, "设备名称");
        var bytes = new byte[32];
        random.nextBytes(bytes);
        var token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        var id = UUID.randomUUID().toString();
        db.update("INSERT INTO device_token(id,secret_hash,account_id,name,created_at) VALUES(?,?,?,?,?)",
                id, hash(token), actor.id(), name, Instant.now().toString());
        return Map.of("id", id, "name", name, "token", token);
    }

    void revokeToken(Actor actor, String id) {
        if (db.update("DELETE FROM device_token WHERE account_id=? AND id=?", actor.id(), id) == 0) {
            throw ApiError.missing("设备令牌不存在");
        }
    }

    static String requiredText(String value, int max, String label) {
        if (value == null || value.isBlank() || value.length() > max) {
            throw ApiError.invalid(label + "不能为空且最多 " + max + " 个字符");
        }
        return value.trim();
    }

    private static String hash(String data) {
        try {
            return Base64.getEncoder().encodeToString(
                    MessageDigest.getInstance("SHA-256").digest(data.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
