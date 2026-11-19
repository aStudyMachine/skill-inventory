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

    @GetMapping("/admin/skills/{name}")
    @Transactional(readOnly = true)
    public Inventory.Draft draft(@PathVariable String name) {
        return inventory.draft(name);
    }

    @PostMapping("/admin/skills")
    @ResponseStatus(HttpStatus.CREATED)
    SkillPackage.Metadata create(@RequestBody Inventory.DraftInput input) {
        return inventory.create(input);
    }

    @PutMapping("/admin/skills/{name}")
    SkillPackage.Metadata edit(@PathVariable String name, @RequestBody Inventory.DraftInput input) {
        return inventory.edit(name, input);
    }

    @PutMapping(value = "/admin/skills/{name}/package", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    SkillPackage.Metadata replace(@PathVariable String name, @RequestParam("file") MultipartFile file) throws IOException {
        return inventory.replace(name, file.getBytes());
    }

    @PostMapping("/admin/skills/{name}/releases")
    @ResponseStatus(HttpStatus.CREATED)
    void publish(@PathVariable String name, @RequestBody Inventory.Publication input) {
        inventory.publish(name, input.version());
    }

    @GetMapping("/admin/skills/{name}/releases/{version}")
    Map<String, Object> history(@PathVariable String name, @PathVariable String version) {
        var release = inventory.history(name, version);
        var result = new java.util.LinkedHashMap<>(release.metadata());
        result.put("source", release.source());
        return result;
    }

    @GetMapping("/admin/skills/{name}/releases/{version}/package")
    ResponseEntity<byte[]> historyPackage(@PathVariable String name, @PathVariable String version) {
        return zip(inventory.history(name, version));
    }

    @PutMapping("/admin/skills/{name}/roles")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void grant(@PathVariable String name, @RequestBody Accounts.Ids roles) {
        inventory.grant(name, roles.ids());
    }

    @DeleteMapping("/admin/skills/{name}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable String name) {
        inventory.delete(name);
    }

    @GetMapping("/skills")
    @Transactional(readOnly = true)
    public List<Map<String, Object>> available(HttpServletRequest request) {
        return inventory.available(accounts.consumer(request));
    }

    @GetMapping("/skills/{name}")
    @Transactional(readOnly = true)
    public Map<String, Object> metadata(HttpServletRequest request, @PathVariable String name,
                                        @RequestParam(required = false) String version) {
        return inventory.published(accounts.consumer(request), name, version).metadata();
    }

    @GetMapping("/skills/{name}/versions")
    @Transactional(readOnly = true)
    public List<Map<String, Object>> versions(HttpServletRequest request, @PathVariable String name) {
        return inventory.versions(accounts.consumer(request), name);
    }

    @GetMapping("/skills/{name}/content")
    @Transactional(readOnly = true)
    public ResponseEntity<String> content(HttpServletRequest request, @PathVariable String name,
                                           @RequestParam(required = false) String version) {
        var release = inventory.published(accounts.consumer(request), name, version);
        return ResponseEntity.ok().header("X-Skill-Version", release.version())
                .contentType(MediaType.parseMediaType("text/plain;charset=UTF-8")).body(release.source());
    }

    @GetMapping("/skills/{name}/package")
    @Transactional(readOnly = true)
    public ResponseEntity<byte[]> download(HttpServletRequest request, @PathVariable String name,
                                            @RequestParam(required = false) String version) {
        return zip(inventory.published(accounts.consumer(request), name, version));
    }

    private static ResponseEntity<byte[]> zip(Inventory.Published release) {
        return ResponseEntity.ok().header("X-Skill-Version", release.version())
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"" + release.name() + "-" + release.version() + ".zip\"")
                .contentType(MediaType.parseMediaType("application/zip")).body(release.archive());
    }
}
