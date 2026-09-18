import java.nio.file.*;
import java.net.*;
import java.util.*;

class JavaFlywayInterop {
    public static void main(String[] args) throws Exception {
        Path root = Path.of(args[0]);
        List<URL> jars = new ArrayList<>();
        try (var paths = Files.walk(root.resolve(".m2-test"))) {
            for (Path p : paths.filter(p -> p.toString().endsWith(".jar")).toList()) jars.add(p.toUri().toURL());
        }
        try (var loader = new URLClassLoader(jars.toArray(URL[]::new), ClassLoader.getPlatformClassLoader())) {
            Thread.currentThread().setContextClassLoader(loader);
            var input = new Scanner(System.in);
            String user = input.nextLine(), password = input.nextLine();
            Class<?> flyway = Class.forName("org.flywaydb.core.Flyway", true, loader);
            Object config = flyway.getMethod("configure").invoke(null);
            Class<?> type = config.getClass();
            type.getMethod("dataSource", String.class, String.class, String.class).invoke(config, args[1], user, password);
            type.getMethod("locations", String[].class).invoke(config, (Object)new String[]{"filesystem:"+root.resolve("bemodel-server/src/main/resources/db/migration").toString().replace('\\','/')});
            type.getMethod("placeholders", Map.class).invoke(config, Map.of("demo_db_username", user, "demo_db_password", password));
            Object instance = type.getMethod("load").invoke(config);
            Object result = flyway.getMethod("migrate").invoke(instance);
            System.out.println("MIGRATIONS:"+result.getClass().getField("migrationsExecuted").get(result));
        }
    }
}
