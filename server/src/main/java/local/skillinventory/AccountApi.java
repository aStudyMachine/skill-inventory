package local.skillinventory;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
class AccountApi {
    private final Accounts accounts;

    AccountApi(Accounts accounts) {
        this.accounts = accounts;
    }

    @PostMapping("/session")
    Accounts.Actor login(HttpServletRequest request, @RequestBody Accounts.Credentials input) {
        return accounts.signIn(request, input);
    }

    @GetMapping("/session")
    Accounts.Actor current(HttpServletRequest request) {
        return accounts.browser(request);
    }

    @GetMapping("/device")
    Accounts.Actor device(HttpServletRequest request) {
        return accounts.consumer(request);
    }

    @DeleteMapping("/session")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void logout(HttpServletRequest request) {
        var session = request.getSession(false);
        if (session != null) session.invalidate();
    }

    @GetMapping("/device-tokens")
    List<Map<String, Object>> tokens(HttpServletRequest request) {
        return accounts.tokens(accounts.browser(request));
    }

    @PostMapping("/device-tokens")
    @ResponseStatus(HttpStatus.CREATED)
    Map<String, String> issue(HttpServletRequest request, @RequestBody Accounts.Name input) {
        return accounts.issueToken(accounts.browser(request), input.name());
    }

    @DeleteMapping("/device-tokens/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void revoke(HttpServletRequest request, @PathVariable String id) {
        accounts.revokeToken(accounts.browser(request), id);
    }

    @GetMapping("/admin/accounts")
    List<Map<String, Object>> accounts() {
        return accounts.listAccounts();
    }

    @PostMapping("/admin/accounts")
    @ResponseStatus(HttpStatus.CREATED)
    void createAccount(@RequestBody Accounts.Credentials input) {
        accounts.create(input, false);
    }

    @PutMapping("/admin/accounts/{id}/roles")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void assign(@PathVariable long id, @RequestBody Accounts.Ids input) {
        accounts.assignRoles(id, input.ids());
    }

    @GetMapping("/admin/roles")
    List<Map<String, Object>> roles() {
        return accounts.listRoles();
    }

    @PostMapping("/admin/roles")
    @ResponseStatus(HttpStatus.CREATED)
    void createRole(@RequestBody Accounts.Name input) {
        accounts.createRole(input.name());
    }
}

@Component
class ApiRequestGuard implements org.springframework.web.servlet.HandlerInterceptor,
        org.springframework.web.servlet.config.annotation.WebMvcConfigurer {
    private final Accounts accounts;

    ApiRequestGuard(Accounts accounts) {
        this.accounts = accounts;
    }

    @Override
    public void addInterceptors(org.springframework.web.servlet.config.annotation.InterceptorRegistry registry) {
        registry.addInterceptor(this).addPathPatterns("/api/v1/**");
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        response.setHeader("Cache-Control", "no-store");
        if (!List.of("GET", "HEAD", "OPTIONS").contains(request.getMethod())
                && !"1".equals(request.getHeader("X-Skill-Inventory"))) {
            throw new ApiError(403, "request_header_required", "缺少操作请求头");
        }
        if (request.getServletPath().startsWith("/api/v1/admin/")) accounts.administrator(request);
        return true;
    }
}
