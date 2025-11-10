(function () {
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

  function renderMermaidDiagrams() {
    if (typeof mermaid === "undefined") {
      return;
    }

    const mermaidElements = document.querySelectorAll(".mermaid");
    if (!mermaidElements.length) {
      return;
    }

    mermaidElements.forEach((element) => {
      element.removeAttribute("data-processed");
    });

    mermaid.initialize({
      startOnLoad: false,
      theme: getMermaidTheme(),
    });

    mermaid.init(undefined, mermaidElements);
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(renderMermaidDiagrams);
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
          break;
        }
      }
    });

    observer.observe(bodyElement, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderMermaidDiagrams);
  } else {
    renderMermaidDiagrams();
  }
})();
