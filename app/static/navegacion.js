(() => {
    const busquedaGlobal = document.getElementById("busqueda-global");
    document.addEventListener("keydown", (evento) => {
        if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "k") {
            evento.preventDefault();
            busquedaGlobal?.focus();
            busquedaGlobal?.select();
        } else if (evento.key === "Escape" && document.activeElement === busquedaGlobal) {
            busquedaGlobal.blur();
        }
    });

    const sidebar = document.getElementById("sidebar-principal");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    if (sidebar && sidebarToggle) {
        const vistaMovil = window.matchMedia("(max-width: 800px)");
        let temporizadorPlegado = null;
        let enfoquePorPuntero = false;

        function actualizarBotonMenu(expandido) {
            sidebarToggle.setAttribute("aria-expanded", String(expandido));
            sidebarToggle.setAttribute("aria-label", expandido ? "Contraer barra lateral" : "Expandir barra lateral");
            sidebarToggle.title = expandido ? "Contraer" : "Expandir";
        }

        function plegarAutomaticamente(demora = 10000) {
            window.clearTimeout(temporizadorPlegado);
            if (vistaMovil.matches || sidebar.classList.contains("is-collapsed")) return;
            temporizadorPlegado = window.setTimeout(() => {
                if (sidebar.contains(document.activeElement)) {
                    plegarAutomaticamente();
                    return;
                }
                sidebar.classList.add("is-collapsed");
                actualizarBotonMenu(false);
            }, demora);
        }

        function cambiarMenu(expandido) {
            if (vistaMovil.matches) return;
            sidebar.classList.toggle("is-collapsed", !expandido);
            actualizarBotonMenu(expandido);
            window.clearTimeout(temporizadorPlegado);
            if (expandido) plegarAutomaticamente();
        }

        function ajustarVista() {
            window.clearTimeout(temporizadorPlegado);
            if (vistaMovil.matches) {
                sidebar.classList.remove("is-collapsed");
                actualizarBotonMenu(true);
            } else {
                sidebar.classList.add("is-collapsed");
                actualizarBotonMenu(false);
            }
        }

        sidebarToggle.addEventListener("click", () => {
            cambiarMenu(sidebar.classList.contains("is-collapsed"));
        });
        sidebar.addEventListener("click", (evento) => {
            if (sidebar.classList.contains("is-collapsed") && evento.target === sidebar) {
                cambiarMenu(true);
            } else if (!sidebar.classList.contains("is-collapsed")) {
                plegarAutomaticamente();
            }
        });
        sidebar.addEventListener("pointermove", () => {
            if (!sidebar.classList.contains("is-collapsed")) plegarAutomaticamente();
        });
        sidebar.addEventListener("pointerleave", () => {
            if (!sidebar.classList.contains("is-collapsed")) plegarAutomaticamente(1400);
        });
        // El foco llega antes del clic; expandir ahí desplazaría el enlace bajo el puntero.
        sidebar.addEventListener("pointerdown", () => { enfoquePorPuntero = true; }, true);
        document.addEventListener("pointerup", () => { enfoquePorPuntero = false; }, true);
        document.addEventListener("pointercancel", () => { enfoquePorPuntero = false; }, true);
        sidebar.addEventListener("focusin", (evento) => {
            if (sidebar.classList.contains("is-collapsed")) {
                if (!enfoquePorPuntero && evento.target !== sidebarToggle) cambiarMenu(true);
            }
            else plegarAutomaticamente();
        });
        sidebar.addEventListener("focusout", (evento) => {
            if (!sidebar.contains(evento.relatedTarget)) plegarAutomaticamente(1400);
        });
        document.addEventListener("pointerdown", (evento) => {
            if (!vistaMovil.matches && !sidebar.contains(evento.target)) cambiarMenu(false);
        });
        document.addEventListener("keydown", (evento) => {
            if (evento.key === "Escape" && !vistaMovil.matches && !sidebar.classList.contains("is-collapsed")) {
                cambiarMenu(false);
            } else if (!vistaMovil.matches && !sidebar.classList.contains("is-collapsed")) {
                plegarAutomaticamente();
            }
        });
        vistaMovil.addEventListener("change", ajustarVista);
        ajustarVista();
    }
})();
