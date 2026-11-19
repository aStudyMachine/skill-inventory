package local.skillinventory;

import java.io.ByteArrayOutputStream;
import java.net.CookieManager;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.datasource.url=jdbc:sqlite::memory:", "inventory.admin-password=integration-password"})
class InventoryHttpTest {
    @LocalServerPort
    int port;
    private static final JsonMapper JSON = new JsonMapper();
    private static final String SOURCE = "---\nname: smoke\ndescription: 示例\n---\n\n";

    @Test
    void publishedVersionsAreImmutableAndHighestVersionUsesNumericComparison() throws Exception {
        var admin = login("admin", "integration-password");
        create(admin, "release-smoke", SOURCE + "旧版");
        assertThat(admin.get("/skills/release-smoke", 404).path("code").asString()).isEqualTo("skill_unavailable");
        publish(admin, "release-smoke", "1.5.1");
        admin.send("PUT", "/admin/skills/release-smoke", draft("release-smoke", SOURCE + "新版"), 200);
        var history = admin.get("/admin/skills/release-smoke", 200);
        assertThat(history.at("/skill/status").asString()).isEqualTo("modified");
        assertThat(admin.request("GET", "/skills/release-smoke/content", null, null, true).body())
                .endsWith("旧版");
        publish(admin, "release-smoke", "2.0.0");
        publish(admin, "release-smoke", "1.10.0");
        assertThat(admin.get("/skills/release-smoke", 200).path("version").asString()).isEqualTo("2.0.0");
        assertThat(admin.get("/skills/release-smoke/versions", 200).get(1).path("version").asString())
                .isEqualTo("1.10.0");
        assertThat(admin.get("/skills/release-smoke?version=1.5.1", 200).path("version").asString())
                .isEqualTo("1.5.1");
        admin.send("POST", "/admin/skills/release-smoke/releases", Map.of("version", "2.0.0"), 409);
        assertThat(admin.get("/skills/release-smoke?version=2.0.1", 404).path("code").asString())
                .isEqualTo("version_unavailable");
        admin.send("DELETE", "/admin/skills/release-smoke", null, 204);
        admin.get("/skills/release-smoke/package?version=1.5.1", 404);
        assertThat(admin.get("/admin/skills/release-smoke/releases/1.5.1", 200).path("source").asString())
                .endsWith("旧版");
    }

    @Test
    void rolesApplyToAllReadRoutesAndLogoutIsImmediate() throws Exception {
        var admin = login("admin", "integration-password");
        admin.send("POST", "/admin/accounts", Map.of("username", "demo-dev", "password", "8".repeat(8)), 400);
        admin.send("POST", "/admin/accounts", Map.of("username", "reader-a", "password", "reader-a-password"), 201);
        admin.send("POST", "/admin/accounts", Map.of("username", "reader-b", "password", "reader-b-password"), 201);
        admin.send("POST", "/admin/roles", Map.of("name", "研发"), 201);
        admin.send("POST", "/admin/roles", Map.of("name", "测试"), 201);
        var roles = admin.get("/admin/roles", 200);
        var accounts = admin.get("/admin/accounts", 200);
        long dev = id(roles, "name", "研发"), qa = id(roles, "name", "测试");
        admin.send("PUT", "/admin/accounts/" + id(accounts, "username", "reader-a") + "/roles",
                Map.of("ids", List.of(dev, qa)), 204);
        admin.send("PUT", "/admin/accounts/" + id(accounts, "username", "reader-b") + "/roles",
                Map.of("ids", List.of(qa)), 204);
        for (var roleSkill : Map.of("dev-skill", dev, "qa-skill", qa).entrySet()) {
            create(admin, roleSkill.getKey(), SOURCE);
            publish(admin, roleSkill.getKey(), "1.0.0");
            publish(admin, roleSkill.getKey(), "2.0.0");
            admin.send("PUT", "/admin/skills/" + roleSkill.getKey() + "/roles", Map.of("ids", List.of(roleSkill.getValue())), 204);
        }
        var reader = login("reader-a", "reader-a-password");
        var other = login("reader-b", "reader-b-password");
        assertThat(skillNames(reader.get("/skills", 200))).containsExactly("dev-skill", "qa-skill");
        assertThat(skillNames(other.get("/skills", 200))).containsExactly("qa-skill");
        other.get("/admin/skills", 403);
        other.get("/skills/dev-skill/package?version=1.0.0", 404);

        var desktop = clientLogin("reader-a", "reader-a-password");
        desktop.get("/admin/skills", 401);
        var download = desktop.request("GET", "/skills/dev-skill/package?version=1.0.0", null, null, true);
        assertThat(download.statusCode()).isEqualTo(200);
        assertThat(download.headers().firstValue("X-Skill-Version")).contains("1.0.0");
        admin.send("PUT", "/admin/skills/dev-skill/roles", Map.of("ids", List.of()), 204);
        for (var suffix : List.of("", "/versions", "/content?version=1.0.0", "/package?version=1.0.0")) {
            desktop.get("/skills/dev-skill" + suffix, 404);
        }
        assertThat(skillNames(desktop.get("/skills", 200))).containsExactly("qa-skill");
        desktop.send("DELETE", "/client-session", null, 204);
        assertThat(desktop.get("/skills", 401).path("code").asString()).isEqualTo("client_login_required");
        reader.get("/skills", 200);

        var id = id(accounts, "username", "reader-a");
        desktop = clientLogin("reader-a", "reader-a-password");
        admin.send("PUT", "/admin/accounts/" + id + "/password", Map.of("password", "changed-test-password"), 204);
        desktop.get("/client-session", 401);
        reader.get("/session", 401);
        desktop = clientLogin("reader-a", "changed-test-password");
        admin.send("PUT", "/admin/accounts/" + id + "/status", Map.of("enabled", false), 204);
        desktop.get("/client-session", 401);
        new Requests(null).send("POST", "/client-session",
                Map.of("username", "reader-a", "password", "changed-test-password"), 401);
        admin.send("PUT", "/admin/accounts/" + id + "/status", Map.of("enabled", true), 204);
        desktop.get("/client-session", 401);
    }

    @Test
    void packageImportKeepsResourcesAndRejectsUnsafePaths() throws Exception {
        var admin = login("admin", "integration-password");
        create(admin, "zip-skill", SOURCE);
        var path = "/admin/skills/zip-skill/package";
        assertThat(importZip(admin, path, "../escape.txt").statusCode()).isEqualTo(400);
        assertThat(importZip(admin, path, ".SKILL-INVENTORY.JSON").statusCode()).isEqualTo(400);
        assertThat(importZip(admin, path, "resources/template.txt").statusCode()).isEqualTo(200);
        admin.send("PUT", "/admin/skills/zip-skill", draft("zip-skill", SOURCE + "修改正文"), 200);
        publish(admin, "zip-skill", "1.0.0");
        assertThat(admin.get("/skills/zip-skill", 200).path("files").toString())
                .contains("resources/template.txt");
        assertThat(admin.get("/admin/skills?q=ZIP-SKI", 200).size()).isEqualTo(1);
        var blocked = admin.request("DELETE", "/admin/skills/zip-skill", null, null, false);
        assertThat(blocked.statusCode()).isEqualTo(403);
    }

    private HttpResponse<String> importZip(Requests admin, String path, String resource) throws Exception {
        var output = new ByteArrayOutputStream();
        try (var zip = new ZipOutputStream(output)) {
            for (var item : Map.of("SKILL.md", SOURCE.replace("name: smoke", "name: zip-skill"), resource, "模板内容").entrySet()) {
                zip.putNextEntry(new ZipEntry(item.getKey()));
                zip.write(item.getValue().getBytes(StandardCharsets.UTF_8));
                zip.closeEntry();
            }
        }
        var body = new ByteArrayOutputStream();
        body.write(("--test\r\nContent-Disposition: form-data; name=\"file\"; filename=\"skill.zip\"\r\n"
                + "Content-Type: application/zip\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        output.writeTo(body);
        body.write("\r\n--test--\r\n".getBytes(StandardCharsets.UTF_8));
        return admin.request("PUT", path, body.toByteArray(), "multipart/form-data; boundary=test", true);
    }

    private long id(JsonNode data, String field, String value) {
        for (var item : data) if (value.equals(item.path(field).asString())) return item.path("id").asLong();
        throw new AssertionError("未找到 " + value);
    }

    private List<String> skillNames(JsonNode data) {
        return data.valueStream().map(item -> item.path("name").asString()).toList();
    }

    private Requests login(String username, String password) throws Exception {
        var browser = new Requests(null);
        browser.send("POST", "/session", Map.of("username", username, "password", password), 200);
        return browser;
    }

    @Test
    void frontmatterDeterminesIdentityAndPublishedNamesRemainReserved() throws Exception {
        var admin = login("admin", "integration-password");
        var created = admin.send("POST", "/admin/skills", draft("source-name", SOURCE), 201);
        assertThat(created.path("name").asString()).isEqualTo("source-name");
        assertThat(created.path("description").asString()).isEqualTo("示例");
        assertThat(created.has("slug")).isFalse();
        admin.send("POST", "/admin/skills", draft("source-name", SOURCE), 409);
        admin.send("POST", "/admin/skills", Map.of("source", "# 缺失元数据"), 400);
        admin.send("PUT", "/admin/skills/source-name", draft("renamed", SOURCE), 200);
        admin.get("/admin/skills/source-name", 404);
        publish(admin, "renamed", "1.0.0");
        admin.send("PUT", "/admin/skills/renamed", draft("another", SOURCE), 409);
        admin.send("PUT", "/admin/skills/renamed", draft("renamed", SOURCE.replace("示例", "新描述")), 200);
        assertThat(admin.get("/skills/renamed", 200).path("description").asString()).isEqualTo("示例");
        admin.send("DELETE", "/admin/skills/renamed", null, 204);
        admin.send("POST", "/admin/skills", draft("renamed", SOURCE), 409);
    }

    private Requests clientLogin(String username, String password) throws Exception {
        var anonymous = new Requests(null);
        var response = anonymous.request("POST", "/client-session",
                JSON.writeValueAsBytes(Map.of("username", username, "password", password)),
                "application/json", true);
        assertThat(response.statusCode()).isEqualTo(200);
        return new Requests(response.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0]);
    }

    private Map<String, String> draft(String slug, String source) {
        return Map.of("source", source.replace("name: smoke", "name: " + slug));
    }

    private void create(Requests admin, String slug, String source) throws Exception {
        admin.send("POST", "/admin/skills", draft(slug, source), 201);
    }

    private void publish(Requests admin, String slug, String version) throws Exception {
        admin.send("POST", "/admin/skills/" + slug + "/releases", Map.of("version", version), 201);
    }

    private class Requests {
        private final HttpClient http = HttpClient.newBuilder().cookieHandler(new CookieManager()).build();
        private final String session;

        Requests(String session) { this.session = session; }

        JsonNode get(String path, int status) throws Exception {
            return send("GET", path, null, status);
        }

        JsonNode send(String method, String path, Object input, int status) throws Exception {
            byte[] body = input == null ? null : JSON.writeValueAsBytes(input);
            var response = request(method, path, body, body == null ? null : "application/json", true);
            assertThat(response.statusCode()).as("%s %s", method, path).isEqualTo(status);
            return response.body().isBlank() ? JSON.nullNode() : JSON.readTree(response.body());
        }

        HttpResponse<String> request(String method, String path, byte[] body, String contentType,
                                     boolean guarded) throws Exception {
            var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/v1" + path));
            if (guarded) builder.header("X-Skill-Inventory", "1");
            if (session != null) builder.header("Cookie", session);
            if (contentType != null) builder.header("Content-Type", contentType);
            return http.send(builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofByteArray(body)).build(), HttpResponse.BodyHandlers.ofString());
        }
    }
}
