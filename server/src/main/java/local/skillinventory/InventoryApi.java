package local.skillinventory;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1")
class InventoryApi {
    private final Inventory inventory;
    private final Accounts accounts;

    InventoryApi(Inventory inventory, Accounts accounts) {
        this.inventory = inventory;
        this.accounts = accounts;
    }

    @GetMapping("/admin/skills")
    List<Inventory.Summary> search(@RequestParam(defaultValue = "") String q) {
        return inventory.adminList(q);
    }

    @GetMapping("/admin/skills/{slug}")
    @Transactional(readOnly = true)
    public Inventory.Draft draft(@PathVariable String slug) {
        return inventory.draft(slug);
    }

    @PostMapping("/admin/skills")
    @ResponseStatus(HttpStatus.CREATED)
    void create(@RequestBody Inventory.DraftInput input) {
        inventory.create(input);
    }

    @PutMapping("/admin/skills/{slug}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void edit(@PathVariable String slug, @RequestBody Inventory.DraftInput input) {
        inventory.edit(slug, input);
    }

    @PutMapping(value = "/admin/skills/{slug}/package", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void replace(@PathVariable String slug, @RequestParam("file") MultipartFile file) throws IOException {
        inventory.replace(slug, file.getBytes());
    }

    @PostMapping("/admin/skills/{slug}/releases")
    @ResponseStatus(HttpStatus.CREATED)
    void publish(@PathVariable String slug, @RequestBody Inventory.Publication input) {
        inventory.publish(slug, input.version());
    }

    @GetMapping("/admin/skills/{slug}/releases/{version}")
    Map<String, Object> history(@PathVariable String slug, @PathVariable String version) {
        var release = inventory.history(slug, version);
        var result = new java.util.LinkedHashMap<>(release.metadata());
        result.put("source", release.source());
        return result;
    }

    @GetMapping("/admin/skills/{slug}/releases/{version}/package")
    ResponseEntity<byte[]> historyPackage(@PathVariable String slug, @PathVariable String version) {
        return zip(inventory.history(slug, version));
    }

    @PutMapping("/admin/skills/{slug}/roles")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void grant(@PathVariable String slug, @RequestBody Accounts.Ids roles) {
        inventory.grant(slug, roles.ids());
    }

    @DeleteMapping("/admin/skills/{slug}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable String slug) {
        inventory.delete(slug);
    }

    @GetMapping("/skills")
    @Transactional(readOnly = true)
    public List<Map<String, Object>> available(HttpServletRequest request) {
        return inventory.available(accounts.consumer(request));
    }

    @GetMapping("/skills/{slug}")
    @Transactional(readOnly = true)
    public Map<String, Object> metadata(HttpServletRequest request, @PathVariable String slug,
                                        @RequestParam(required = false) String version) {
        return inventory.published(accounts.consumer(request), slug, version).metadata();
    }

    @GetMapping("/skills/{slug}/versions")
    @Transactional(readOnly = true)
    public List<Map<String, Object>> versions(HttpServletRequest request, @PathVariable String slug) {
        return inventory.versions(accounts.consumer(request), slug);
    }

    @GetMapping("/skills/{slug}/content")
    @Transactional(readOnly = true)
    public ResponseEntity<String> content(HttpServletRequest request, @PathVariable String slug,
                                           @RequestParam(required = false) String version) {
        var release = inventory.published(accounts.consumer(request), slug, version);
        return ResponseEntity.ok().header("X-Skill-Version", release.version())
                .contentType(MediaType.parseMediaType("text/plain;charset=UTF-8")).body(release.source());
    }

    @GetMapping("/skills/{slug}/package")
    @Transactional(readOnly = true)
    public ResponseEntity<byte[]> download(HttpServletRequest request, @PathVariable String slug,
                                            @RequestParam(required = false) String version) {
        return zip(inventory.published(accounts.consumer(request), slug, version));
    }

    private static ResponseEntity<byte[]> zip(Inventory.Published release) {
        return ResponseEntity.ok().header("X-Skill-Version", release.version())
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"" + release.slug() + "-" + release.version() + ".zip\"")
                .contentType(MediaType.parseMediaType("application/zip")).body(release.archive());
    }
}
