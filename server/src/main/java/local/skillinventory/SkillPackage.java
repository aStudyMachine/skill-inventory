package local.skillinventory;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;

record SkillPackage(Map<String, byte[]> files) {
    private static final int SIZE_LIMIT = 16 * 1024 * 1024;
    private static final int FILE_LIMIT = 512;

    static SkillPackage text(String source) {
        return new SkillPackage(Map.of("SKILL.md", source.getBytes(StandardCharsets.UTF_8)));
    }

    static SkillPackage read(byte[] archive) {
        Map<String, byte[]> files = new LinkedHashMap<>();
        Map<String, String> names = new HashMap<>();
        Map<String, Boolean> kinds = new HashMap<>();
        try (var zip = new ZipInputStream(new ByteArrayInputStream(archive))) {
            int remaining = SIZE_LIMIT;
            int count = 0;
            for (ZipEntry entry; (entry = zip.getNextEntry()) != null;) {
                if (++count > FILE_LIMIT) throw ApiError.invalid("ZIP 条目过多");
                var name = entry.getName();
                if (entry.isDirectory()) name = name.substring(0, name.length() - 1);
                checkPath(name, entry.isDirectory(), names, kinds);
                if (entry.isDirectory()) {
                    if (zip.read() != -1) throw ApiError.invalid("ZIP 目录条目包含数据");
                    continue;
                }
                var bytes = zip.readNBytes(remaining + 1);
                remaining -= bytes.length;
                if (remaining < 0) throw ApiError.invalid("ZIP 解压后超过 16 MiB");
                if (files.putIfAbsent(name, bytes) != null) throw ApiError.invalid("ZIP 含重复文件");
            }
        } catch (IOException | IllegalArgumentException e) {
            throw ApiError.invalid("ZIP 无法读取");
        }
        if (!files.containsKey("SKILL.md")) throw ApiError.invalid("ZIP 根目录必须包含 SKILL.md");
        return new SkillPackage(files);
    }

    private static void checkPath(String name, boolean directory, Map<String, String> names,
                                  Map<String, Boolean> kinds) {
        if (name.length() > 220) throw ApiError.invalid("ZIP 路径过长");
        var parts = name.split("/", -1);
        if (parts[0].equalsIgnoreCase(".skill-inventory.json")) {
            throw ApiError.invalid("ZIP 使用了客户端保留的文件名");
        }
        String prefix = "";
        for (int i = 0; i < parts.length; i++) {
            var part = parts[i];
            if (part.isEmpty() || part.endsWith(".") || part.endsWith(" ") || part.chars()
                    .anyMatch(c -> c < 32 || "\\:*?\"<>|".indexOf(c) >= 0)
                    || part.matches("(?i)(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]|CONIN\\$|CONOUT\\$)(\\..*)?")) {
                throw ApiError.invalid("ZIP 含不安全的 Windows 路径");
            }
            prefix += (i == 0 ? "" : "/") + part;
            var key = prefix.toLowerCase(Locale.ROOT);
            var previous = names.putIfAbsent(key, prefix);
            boolean isDirectory = directory || i < parts.length - 1;
            var previousKind = kinds.putIfAbsent(key, isDirectory);
            if ((previous != null && !previous.equals(prefix))
                    || (previousKind != null && previousKind != isDirectory)) {
                throw ApiError.invalid("ZIP 文件路径冲突");
            }
        }
    }

    SkillPackage edit(String source) {
        var copy = new LinkedHashMap<>(files);
        copy.put("SKILL.md", source.getBytes(StandardCharsets.UTF_8));
        if (copy.values().stream().mapToLong(bytes -> bytes.length).sum() > SIZE_LIMIT) {
            throw ApiError.invalid("文件包超过 16 MiB");
        }
        return new SkillPackage(copy);
    }

    String source() {
        try {
            return StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(files.get("SKILL.md"))).toString();
        } catch (IOException e) {
            throw ApiError.invalid("SKILL.md 必须使用 UTF-8");
        }
    }

    void validate() {
        var lines = source().lines().toList();
        int end = lines.size() > 1 ? lines.subList(1, lines.size()).indexOf("---") + 1 : 0;
        if (end == 0 || !lines.getFirst().equals("---")) throw ApiError.invalid("SKILL.md 缺少 YAML 元数据");
        var options = new LoaderOptions();
        options.setAllowDuplicateKeys(false);
        Object metadata;
        try {
            metadata = new Yaml(new SafeConstructor(options)).load(String.join("\n", lines.subList(1, end)));
        } catch (RuntimeException e) {
            throw ApiError.invalid("SKILL.md 的 YAML 元数据无效");
        }
        if (!(metadata instanceof Map<?, ?> map) || !(map.get("name") instanceof String name)
                || !name.matches("[a-z0-9]+(?:-[a-z0-9]+)*") || name.length() > 64
                || !(map.get("description") instanceof String description) || description.isBlank()
                || description.length() > 1024) {
            throw ApiError.invalid("SKILL.md 必须包含有效的 name 和 description");
        }
    }

    List<String> names() {
        return files.keySet().stream().sorted().toList();
    }

    byte[] zip() {
        var output = new ByteArrayOutputStream();
        try (var zip = new ZipOutputStream(output)) {
            for (var file : files.entrySet()) {
                var entry = new ZipEntry(file.getKey());
                entry.setTime(0);
                zip.putNextEntry(entry);
                zip.write(file.getValue());
                zip.closeEntry();
            }
        } catch (IOException e) {
            throw new IllegalStateException("无法写入 Skill 文件包", e);
        }
        return output.toByteArray();
    }
}
