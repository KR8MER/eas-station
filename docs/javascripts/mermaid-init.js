(function () {
  let renderIdCounter = 0;

  function getDocumentBody() {
    return document.body || document.querySelector("body");
  }

  function getMermaidTheme() {
    const body = getDocumentBody();
    if (!body) {
      return "default";
    }

    const scheme = body.getAttribute("data-md-color-scheme");
    if (scheme) {
      return scheme === "slate" ? "dark" : "default";
    }

    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "default";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function extractMermaidCode(element) {
    if (element.dataset && element.dataset.mermaidCode) {
      return element.dataset.mermaidCode;
    }

    const tagName = element.tagName ? element.tagName.toLowerCase() : "";
    let code = "";
    if (tagName === "pre") {
      const codeElement = element.querySelector("code");
      code = codeElement ? codeElement.textContent || "" : element.textContent || "";
    } else {
      code = element.textContent || "";
    }

    return code.trim();
  }

  function ensureMermaidContainer(element, code) {
    if (element.dataset && element.dataset.mermaidCode) {
      element.dataset.mermaidCode = code;
      return element;
    }

    const container = document.createElement("div");
    container.className = "mermaid";
    container.dataset.mermaidCode = code;
    element.replaceWith(container);
    return container;
  }

  function renderMermaidBlock(element) {
    const code = extractMermaidCode(element);
    if (!code) {
      return;
    }

    const container = ensureMermaidContainer(element, code);
    const renderId = `mermaid-${renderIdCounter++}`;

    try {
      mermaid.render(
        renderId,
        code,
        (svgCode, bindFunctions) => {
          container.innerHTML = svgCode;
          if (typeof bindFunctions === "function") {
            bindFunctions(container);
          }
        },
        container
      );
    } catch (error) {
      console.error("Mermaid rendering failed", error);
      container.innerHTML = `<pre class="mermaid-error">${escapeHtml(code)}</pre>`;
    }
  }

  function renderMermaidDiagrams() {
    if (typeof mermaid === "undefined") {
      return;
    }

    const mermaidElements = document.querySelectorAll("pre.mermaid, div.mermaid");
    if (!mermaidElements.length) {
      return;
    }

    mermaid.initialize({
      startOnLoad: false,
      theme: getMermaidTheme(),
      securityLevel: "loose",
    });

    mermaidElements.forEach((element) => {
      if (element.removeAttribute) {
        element.removeAttribute("data-processed");
      }
      renderMermaidBlock(element);
    });
  }

  function subscribeToDocumentReady() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", renderMermaidDiagrams);
    } else {
      renderMermaidDiagrams();
    }
  }

  const hasDocumentSubscription =
    typeof document$ !== "undefined" && document$ && typeof document$.subscribe === "function";

  if (hasDocumentSubscription) {
    document$.subscribe(renderMermaidDiagrams);
    renderMermaidDiagrams();
  } else {
    subscribeToDocumentReady();
  }

  const schemeMediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (schemeMediaQuery) {
    if (typeof schemeMediaQuery.addEventListener === "function") {
      schemeMediaQuery.addEventListener("change", renderMermaidDiagrams);
    } else if (typeof schemeMediaQuery.addListener === "function") {
      schemeMediaQuery.addListener(renderMermaidDiagrams);
    }
  }

  const bodyElement = getDocumentBody();
  if (bodyElement) {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "attributes" && mutation.attributeName === "data-md-color-scheme") {
          renderMermaidDiagrams();
          return;
        }
      }
    });

    observer.observe(bodyElement, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
  }

})();
