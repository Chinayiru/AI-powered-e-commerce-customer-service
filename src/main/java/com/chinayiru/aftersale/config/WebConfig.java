package com.chinayiru.aftersale.config;

import java.io.IOException;

import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.web.servlet.resource.PathResourceResolver;

/**
 * 静态页托管 + SPA 路由回退。
 *
 * <p>前端是 history 路由（/runs、/eval 刷新时浏览器直接请求服务器），dist 里并没有
 * 这些文件；缺省会 404。这里只对"看起来像页面"的路径回退 index.html，
 * 带扩展名的资源（.js/.css/.svg）缺失仍然 404，免得把 404 伪装成 200 让人查不到。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/**")
            .addResourceLocations("classpath:/static/")
            .resourceChain(true)
            .addResolver(new PathResourceResolver() {
                @Override
                protected Resource getResource(String resourcePath, Resource location) throws IOException {
                    Resource requested = location.createRelative(resourcePath);
                    if (requested.exists() && requested.isReadable()) {
                        return requested;
                    }
                    if (resourcePath.contains(".")) {
                        return null; // 资源缺失就是缺失，不回退成 HTML
                    }
                    Resource index = new ClassPathResource("/static/index.html");
                    return index.exists() ? index : null;
                }
            });
    }
}
