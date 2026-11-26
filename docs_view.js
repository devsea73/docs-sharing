(() => {
    if (location.hostname !== "docs.google.com" ||
        !/^\/document\/(?:u\/\d+\/)?d\/[\w-]+\/(?:edit|view)\/?$/.test(location.pathname)) {
        return;
    }

    const style = document.createElement("style");
    style.textContent = `
        html, body, .kix-appview, .kix-appview-editor, .kix-page, .kix-page-paginated {
            background: #fff !important;
        }
        #docs-chrome, #docs-header, #docs-titlebar-container, #docs-menubars,
        #docs-toolbar-wrapper, #docs-rulers, .docs-ruler, .docs-ruler-container,
        .kix-ruler-container, .docs-butterbar-container, .docs-banner,
        .docs-material-gm-ltr-butterbar, .docs-gm #docs-branding-container,
        #docs-branding-container, #docs-sidekick, .docs-sidekick,
        .docs-companion-app-switcher-container, .companion-guest-app-switcher,
        .companion-collapser-button-container, .docs-explore-widget,
        .navigation-widget, .kix-document-outline, .kix-minimap {
            display: none !important;
        }
        #docs-editor-container, #docs-editor, .kix-appview, .kix-appview-editor-container,
        .kix-appview-editor {
            inset: 0 !important;
            margin: 0 !important;
            width: 100% !important;
        }
        .kix-appview-editor {
            height: 100vh !important;
            overflow-x: hidden !important;
            scrollbar-width: none;
        }
        .kix-rotatingtilemanager {
            left: var(--support-page-left, 0px) !important;
        }
        .kix-page, .kix-page-paginated, .kix-page-bottom {
            box-shadow: none !important;
            border-color: transparent !important;
        }
    `;

    // The live editor creates its canvas asynchronously. Leave sign-in,
    // permissions, and loading pages intact until an editor is available.
    globalThis.supportAppMetrics = () => {
        const editor = document.querySelector(".kix-appview-editor");
        const page = editor?.querySelector(".kix-page-paginated, .kix-page");
        if (!page || !page.offsetWidth) {
            return null;
        }
        if (!style.isConnected) {
            (document.head || document.documentElement).append(style);
            window.dispatchEvent(new Event("resize"));
        }
        const tiles = page.closest(".kix-rotatingtilemanager");
        if (tiles) {
            const gutter = tiles.getBoundingClientRect().left - page.getBoundingClientRect().left;
            tiles.style.setProperty("--support-page-left", `${gutter}px`);
        }
        if (editor.scrollLeft) {
            editor.scrollLeft = 0;
        }
        return {
            pageWidth: page.getBoundingClientRect().width,
            viewportWidth: window.innerWidth,
        };
    };

    window.addEventListener("wheel", (event) => {
        if (event.ctrlKey && style.isConnected) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, {capture: true, passive: false});
})();
