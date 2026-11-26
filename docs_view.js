(() => {
    if (location.hostname !== "docs.google.com" ||
        !/^\/document\/(?:u\/\d+\/)?d\/[\w-]+\/(?:edit|view)\/?$/.test(location.pathname)) {
        return;
    }

    const style = document.createElement("style");
    style.textContent = `
        html, body, .kix-appview, .kix-appview-editor, .kix-page, .kix-page-paginated {
            background: #111923 !important;
            color: #f4f7ff !important;
        }
        canvas.kix-canvas-tile-content {
            filter: invert(1) hue-rotate(180deg) !important;
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
            height: var(--support-editor-height, 100vh) !important;
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
        .kix-appview-editor.anti-mirror-editor {
            overflow-y: hidden !important;
        }
    `;

    const editorElement = () => document.querySelector(".kix-appview-editor");
    const pagesIn = editor => {
        const paginated = editor.querySelectorAll(".kix-page-paginated");
        return [...(paginated.length ? paginated : editor.querySelectorAll(".kix-page"))];
    };

    let mirrorEditor;
    let mirrorPosition = 0;

    function moveEditor(editor, position) {
        const available = Math.max(0, editor.scrollHeight - editor.clientHeight);
        const target = Math.min(position, available);
        if (Math.abs(editor.scrollTop - target) > 1) editor.scrollTop = target;
        return target;
    }

    function enforceMirrorPosition() {
        moveEditor(mirrorEditor, mirrorPosition);
    }

    function positionMirror(editor, position, sharedHeight) {
        if (mirrorEditor !== editor) {
            mirrorEditor?.removeEventListener("scroll", enforceMirrorPosition);
            mirrorEditor = editor;
            mirrorEditor.addEventListener("scroll", enforceMirrorPosition, {passive: true});
        }
        mirrorPosition = position;
        editor.classList.add("anti-mirror-editor");
        const height = Math.min(window.innerHeight, sharedHeight || window.innerHeight);
        editor.style.setProperty("--support-editor-height", `${height}px`);
        enforceMirrorPosition();
    }

    globalThis.supportAppScrollMirror = (position, sharedHeight) => {
        const editor = editorElement();
        if (editor && style.isConnected) positionMirror(editor, position, sharedHeight);
    };

    // The live editor creates its canvas asynchronously. Leave sign-in,
    // permissions, and loading pages intact until an editor is available.
    globalThis.supportAppMetrics = (position = null, sharedHeight = 0, mirrored = false) => {
        const editor = editorElement();
        if (!editor || !pagesIn(editor).some(page => page.offsetWidth)) {
            return null;
        }
        if (!style.isConnected) {
            (document.head || document.documentElement).append(style);
            window.dispatchEvent(new Event("resize"));
        }
        let expected = position;
        if (mirrored) {
            positionMirror(editor, position, sharedHeight);
        } else if (position !== null) {
            expected = moveEditor(editor, position);
        }
        const editorBounds = editor.getBoundingClientRect();
        const pages = pagesIn(editor);
        const visiblePage = pages.find(node => {
            const bounds = node.getBoundingClientRect();
            return bounds.top < editorBounds.bottom && bounds.bottom > editorBounds.top;
        });
        const page = visiblePage || pages[0];
        if (!page) return null;
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
            viewportHeight: window.innerHeight,
            scrollHeight: editor.scrollHeight,
            scrollTop: editor.scrollTop,
            positionReady: expected === null || (Math.abs(editor.scrollTop - expected) <= 3 &&
                (!mirrored || !!visiblePage)),
        };
    };

    window.addEventListener("wheel", (event) => {
        if (event.ctrlKey && style.isConnected) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, {capture: true, passive: false});
})();
