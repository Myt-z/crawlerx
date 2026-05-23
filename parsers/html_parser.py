"""
HTML 解析器 —— CSS 选择器 / XPath 提取数据
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup
from loguru import logger
from parsel import Selector

import config


class HTMLParser:
    """
    HTML 数据提取器，支持 CSS 选择器 + XPath 两种语法。
    底层基于 parsel（比 BeautifulSoup 快 5-10 倍）。
    """

    def __init__(self, html: str = None, url: str = None):
        self.html = html
        self.url = url
        self._selector: Optional[Selector] = None
        if html:
            self._selector = Selector(text=html)

    def set_html(self, html: str, url: str = None):
        self.html = html
        self.url = url
        self._selector = Selector(text=html)

    # ---- 单个提取 ----

    def extract(
        self,
        html_or_selector: str | Selector,
        selector: str,
        attr: str = "text",
    ) -> Any:
        """提取单个值"""
        sel = self._to_selector(html_or_selector)

        if attr == "text":
            result = sel.css(f"{selector}::text").get()
        elif attr == "html":
            result = sel.css(selector).get()
        elif attr == "inner":
            result = "".join(sel.css(f"{selector} *::text").getall())
        else:
            result = sel.css(selector).attrib.get(attr) if sel.css(selector) else None

        return result.strip() if isinstance(result, str) else result

    def extract_xpath(self, html_or_selector, xpath: str) -> Any:
        """XPath 提取"""
        sel = self._to_selector(html_or_selector)
        result = sel.xpath(xpath).get()
        return result.strip() if isinstance(result, str) else result

    # ---- 批量提取 ----

    def extract_list(
        self,
        html_or_selector: str | Selector,
        selector: str,
        attr: str = "text",
    ) -> list[str]:
        """提取多个匹配项"""
        sel = self._to_selector(html_or_selector)

        if attr == "text":
            return [v.strip() for v in sel.css(f"{selector}::text").getall()]
        elif attr == "html":
            return sel.css(selector).getall()
        else:
            return [
                el.attrib.get(attr, "")
                for el in sel.css(selector)
            ]

    # ---- 规则解析（最常用） ----

    def parse_list(self, html: str, rules: dict, url: str = None) -> list[dict]:
        """
        按 rules 字典批量提取结构化数据。

        rules 格式:
        {
            "title":   {"selector": "h1.title", "attr": "text"},
            "price":   {"selector": "span.price", "attr": "text"},
            "link":    {"selector": "a", "attr": "href"},
            "tags":    {"selector": "span.tag", "attr": "text", "multiple": True},
        }

        url 参数用于自适应重定位的指纹存储（可选）。

        返回 list[dict]，每个 dict 对应一个容器元素。
        """
        if url:
            self.url = url

        data = []

        # 自动检测容器：找到所有规则中第一个 selector 的共同父级
        container_selector = self._find_container(rules)

        # 尝试从指纹库加载已知的工作选择器
        if not container_selector and config.ADAPTIVE_ENABLED:
            container_selector = self._load_fingerprint(rules)

        if container_selector:
            # 有明确的容器
            sel = Selector(text=html)
            containers = sel.css(container_selector)

            # ---- 自适应重定位：容器选择器返回空时尝试回退 ----
            if not containers and config.ADAPTIVE_ENABLED:
                fallback = self._find_fallback_container(html, rules, container_selector)
                if fallback:
                    logger.info(f"[自适应] 容器回退: {container_selector} -> {fallback}")
                    containers = sel.css(fallback)
                    if containers:
                        container_selector = fallback

            for item_sel in containers:
                row = {}
                for field, rule in rules.items():
                    row[field] = self._apply_rule(item_sel, rule)
                data.append(row)

            # 保存成功的选择器指纹
            if data and config.ADAPTIVE_ENABLED and self.url:
                self._save_fingerprint(rules, container_selector)
        else:
            # 无容器，按每条规则单独提取后 zip
            sel = Selector(text=html)
            columns = {}
            max_len = 0
            for field, rule in rules.items():
                values = self._apply_rule_multi(sel, rule)
                columns[field] = values
                max_len = max(max_len, len(values))

            for i in range(max_len):
                row = {}
                for field in rules:
                    vals = columns.get(field, [])
                    row[field] = vals[i] if i < len(vals) else ""
                data.append(row)

        return data

    def _apply_rule(self, sel: Selector, rule: dict) -> Any:
        """在单个容器元素上应用提取规则"""
        selector = rule.get("selector", "")
        attr = rule.get("attr", "text")
        multiple = rule.get("multiple", False)

        if multiple:
            return self.extract_list(sel, selector, attr)
        return self.extract(sel, selector, attr)

    def _apply_rule_multi(self, sel: Selector, rule: dict) -> list:
        """在根选择器上批量提取（无容器时使用）"""
        selector = rule.get("selector", "")
        attr = rule.get("attr", "text")
        return self.extract_list(sel, selector, attr)

    def _find_container(self, rules: dict) -> Optional[str]:
        """
        智能检测容器选择器：取所有规则 CSS 选择器的最长公共前缀。
        如规则 "div.quote span.text", "div.quote small.author" → 容器 "div.quote"
        """
        selectors = [r.get("selector", "") for r in rules.values() if r.get("selector")]
        if not selectors:
            return None

        # 按空格拆分每个选择器，取最短的 token 数
        split_sels = [s.split() for s in selectors]
        min_len = min(len(tokens) for tokens in split_sels)

        if min_len < 2:
            return None  # 单级选择器，无法提取容器

        # 找公共前缀
        common = []
        for i in range(min_len - 1):  # 最后一个是目标元素，不能作为容器
            token = split_sels[0][i]
            if all(tokens[i] == token for tokens in split_sels):
                common.append(token)
            else:
                break

        return " ".join(common) if common else None

    # ---- 自适应重定位 ----

    def _find_fallback_container(
        self, html: str, rules: dict, original_selector: str
    ) -> Optional[str]:
        """当原始容器选择器返回空时，尝试前缀回退寻找替代容器。"""
        tokens = original_selector.split()
        if len(tokens) < 2:
            return None

        sel = Selector(text=html)
        # 逐级缩短选择器
        for i in range(len(tokens) - 1, 0, -1):
            candidate = " ".join(tokens[:i])
            containers = sel.css(candidate)
            if containers:
                # 验证：短容器内能否匹配到目标元素
                first_rule = list(rules.values())[0]
                target_sel = first_rule.get("selector", "")
                if target_sel:
                    for container in containers[:3]:
                        if container.css(target_sel):
                            return candidate
        return None

    def _get_fingerprint_path(self) -> Optional[Path]:
        """根据 URL 域名获取指纹文件路径。"""
        if not self.url:
            return None
        try:
            from urllib.parse import urlparse
            domain = urlparse(self.url).netloc or "unknown"
            safe_domain = hashlib.md5(domain.encode()).hexdigest()[:12]
            config.ADAPTIVE_FINGERPRINT_DIR.mkdir(parents=True, exist_ok=True)
            return config.ADAPTIVE_FINGERPRINT_DIR / f"{safe_domain}.json"
        except Exception:
            return None

    def _save_fingerprint(self, rules: dict, effective_selector: str):
        """保存成功的选择器指纹，供以后回退使用。"""
        path = self._get_fingerprint_path()
        if not path:
            return
        try:
            fingerprints = {}
            if path.exists():
                fingerprints = json.loads(path.read_text(encoding="utf-8"))
            rule_key = hashlib.md5(
                json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:12]
            fingerprints[rule_key] = {"container_selector": effective_selector}
            path.write_text(
                json.dumps(fingerprints, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_fingerprint(self, rules: dict) -> Optional[str]:
        """加载之前成功的选择器指纹。"""
        path = self._get_fingerprint_path()
        if not path or not path.exists():
            return None
        try:
            fingerprints = json.loads(path.read_text(encoding="utf-8"))
            rule_key = hashlib.md5(
                json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:12]
            entry = fingerprints.get(rule_key)
            if entry:
                return entry.get("container_selector")
        except Exception:
            pass
        return None

    # ---- 翻页辅助 ----

    def next_page_url(self, html: str, current_url: str, selector: str) -> Optional[str]:
        """提取下一页链接"""
        sel = Selector(text=html)
        href = sel.css(f"{selector}::attr(href)").get()
        if not href:
            return None
        # 处理相对路径
        if href.startswith("http"):
            return href
        import urllib.parse
        return urllib.parse.urljoin(current_url, href)

    # ---- 链接提取 ----

    def extract_links(self, html: str, selector: str) -> list[str]:
        """提取所有匹配的链接"""
        return self.extract_list(html, selector, "href")

    # ---- 工具 ----

    def _to_selector(self, source: str | Selector) -> Selector:
        if isinstance(source, Selector):
            return source
        return Selector(text=source)

    def clean_html(self, html: str) -> str:
        """去除 HTML 标签，保留纯文本"""
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator="\n", strip=True)
