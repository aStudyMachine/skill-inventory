package local.skillinventory;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.DependsOn;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@DependsOn("databaseUpgrade")
class Accounts {
    record Actor(long id, String username, boolean admin) {}
    record Credentials(String username, String password) {}
    record Ids(List<Long> ids) {}
    record Name(String name) {}
    record AccountStatus(boolean enabled) {}
    record PasswordChange(String password) {}
    record ClientLogin(Actor actor, String session) {}
    private record Identity(Actor actor, String passwordHash, long revision) {}

    static final String CLIENT_COOKIE = "SkillInventoryClient";

    private static final String SESSION_ACTOR = "inventory-account-id";
    private static final Set<String> DEMO_USERS = Set.of("admin", "demo-dev", "demo-qa", "demo-both");
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

    @org.springframework.beans.factory.annotation.Value("${inventory.demo-initial-password:}")
    private String demoInitialPassword;

    private Identity authenticate(Credentials input) {
        var rows = db.query("""
                SELECT id,username,admin,password_hash,auth_revision FROM account WHERE username=? AND enabled=1
                """, (row, index) -> new Identity(new Actor(row.getLong(1), row.getString(2), row.getBoolean(3)),
                        row.getString(4), row.getLong(5)), input.username());
        if (rows.isEmpty() || !validPasswordSize(input.password())
                || !encoder.matches(input.password(), rows.getFirst().passwordHash())) {
            throw new ApiError(401, "invalid_credentials", "账号或密码错误");
        }
        return rows.getFirst();
    }

    Actor signIn(HttpServletRequest request, Credentials input) {
        var identity = authenticate(input);
        var previous = request.getSession(false);
        if (previous != null) previous.invalidate();
        request.getSession().setAttribute(SESSION_ACTOR, identity.actor().id());
        request.getSession().setAttribute("inventory-auth-revision", identity.revision());
        return identity.actor();
    }

    Actor browser(HttpServletRequest request) {
        var session = request.getSession(false);
        if (session != null && session.getAttribute(SESSION_ACTOR) instanceof Long id
                && session.getAttribute("inventory-auth-revision") instanceof Long revision) {
            var found = actors("SELECT id,username,admin FROM account WHERE id=? AND auth_revision=? AND enabled=1",
                    id, revision);
            if (!found.isEmpty()) return found.getFirst();
        }
        throw new ApiError(401, "login_required", "请先登录");
    }

    @Transactional
    public ClientLogin clientSignIn(Credentials input) {
        var actor = authenticate(input).actor();
        var bytes = new byte[32];
        random.nextBytes(bytes);
        var session = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        db.update("INSERT INTO client_session(secret_hash,account_id) VALUES(?,?)", hash(session), actor.id());
        return new ClientLogin(actor, session);
    }

    Actor client(HttpServletRequest request) {
        var session = clientCookie(request);
        if (session != null && session.matches("[a-zA-Z0-9_-]{43}")) {
            var found = actors("""
                    SELECT a.id,a.username,a.admin FROM client_session s JOIN account a
                      ON a.id=s.account_id WHERE s.secret_hash=? AND a.enabled=1
                    """, hash(session));
            if (!found.isEmpty()) return found.getFirst();
        }
        throw new ApiError(401, "client_login_required", "登录已失效，请重新登录");
    }

    void clientSignOut(HttpServletRequest request) {
        var session = clientCookie(request);
        if (session != null && session.matches("[a-zA-Z0-9_-]{43}")) {
            db.update("DELETE FROM client_session WHERE secret_hash=?", hash(session));
        }
    }

    Actor consumer(HttpServletRequest request) {
        return clientCookie(request) == null ? browser(request) : client(request);
    }

    private static String clientCookie(HttpServletRequest request) {
        var cookies = request.getCookies();
        if (cookies != null) {
            for (var cookie : cookies) if (CLIENT_COOKIE.equals(cookie.getName())) return cookie.getValue();
        }
        return null;
    }

    void administrator(HttpServletRequest request) {
        if (!browser(request).admin()) throw new ApiError(403, "admin_required", "需要管理员权限");
    }

    private List<Actor> actors(String sql, Object... arguments) {
        return db.query(sql, (row, index) -> new Actor(row.getLong(1), row.getString(2), row.getBoolean(3)), arguments);
    }

    void create(Credentials input, boolean admin) {
        if (input.username() == null || !input.username().matches("[a-zA-Z0-9_.-]{1,64}")) {
            throw ApiError.invalid("账号由 1 至 64 位字母、数字、点、下划线或连字符组成");
        }
        if (demoInitialPassword.isEmpty() || !DEMO_USERS.contains(input.username())
                || !demoInitialPassword.equals(input.password())) {
            validatePassword(input.password());
        }
        if (db.update("INSERT INTO account(username,password_hash,admin) VALUES(?,?,?) ON CONFLICT(username) DO NOTHING",
                input.username(), encoder.encode(input.password()), admin) == 0) {
            throw ApiError.conflict("账号已存在");
        }
    }

    private static boolean validPasswordSize(String password) {
        return password != null && password.getBytes(StandardCharsets.UTF_8).length <= 72;
    }

    private static void validatePassword(String password) {
        if (!validPasswordSize(password) || password.length() < 10) {
            throw ApiError.invalid("密码至少 10 个字符，且 UTF-8 编码不超过 72 字节");
        }
    }

    List<Map<String, Object>> listAccounts() {
        var accounts = db.queryForList("SELECT id,username,admin,enabled FROM account ORDER BY username");
        return accounts.stream().<Map<String, Object>>map(account -> {
            var id = ((Number) account.get("id")).longValue();
            return Map.of("id", id, "username", account.get("username"),
                    "admin", ((Number) account.get("admin")).intValue() != 0,
                    "enabled", ((Number) account.get("enabled")).intValue() != 0, "roles", rolesFor(id));
        }).toList();
    }

    @Transactional
    public void changePassword(long id, String password) {
        validatePassword(password);
        if (db.update("UPDATE account SET password_hash=?,auth_revision=auth_revision+1 WHERE id=?",
                encoder.encode(password), id) == 0) throw ApiError.missing("账号不存在");
        db.update("DELETE FROM client_session WHERE account_id=?", id);
    }

    @Transactional
    public void setEnabled(long id, boolean enabled) {
        var found = actors("SELECT id,username,admin FROM account WHERE id=?", id);
        if (found.isEmpty()) throw ApiError.missing("账号不存在");
        if (!enabled && found.getFirst().admin()) throw ApiError.conflict("管理员账号不能停用");
        if (db.update("UPDATE account SET enabled=?,auth_revision=auth_revision+1 WHERE id=? AND enabled<>?",
                enabled, id, enabled) > 0) {
            db.update("DELETE FROM client_session WHERE account_id=?", id);
        }
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
