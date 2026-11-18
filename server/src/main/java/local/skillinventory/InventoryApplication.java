package local.skillinventory;

import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class InventoryApplication {
    public static void main(String[] args) throws Exception {
        var database = Path.of(System.getenv().getOrDefault("INVENTORY_DB", "data/inventory.db"));
        Files.createDirectories(database.toAbsolutePath().getParent());
        SpringApplication.run(InventoryApplication.class, args);
    }
}
