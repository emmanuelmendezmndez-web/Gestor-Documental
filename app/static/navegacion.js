(() => {
    const busquedaGlobal = document.getElementById("busqueda-global");
    if (busquedaGlobal) document.addEventListener("keydown", (evento) => {
        if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "k") {
            evento.preventDefault();
            busquedaGlobal?.focus();
            busquedaGlobal?.select();
        } else if (evento.key === "Escape" && document.activeElement === busquedaGlobal) {
            busquedaGlobal.blur();
        }
    });

    const aviso = document.getElementById("aviso-operacion");
    if (aviso) {
        const cerrar = aviso.querySelector("[data-cerrar-aviso]");
        let posicionPendiente = false;
        const ubicar = () => {
            posicionPendiente = false;
            if (aviso.hidden) return;
            const caja = aviso.getBoundingClientRect();
            const controles = [...document.querySelectorAll(
                ".app-topbar, .sidebar, .auth-header, #contenido-principal :is(input, select, textarea, button, a[href], summary)"
            )].filter(control => !aviso.contains(control))
                .map(control => control.getBoundingClientRect())
                .filter(rect => rect.height && rect.right > caja.left && rect.left < caja.right)
                .sort((a, b) => b.bottom - a.bottom);
            let borde = window.innerHeight - 12;
            for (const rect of controles) {
                if (rect.top < borde && rect.bottom > borde - caja.height) borde = rect.top - 8;
            }
            if (borde - caja.height >= 12) {
                aviso.style.setProperty("--aviso-operacion-separacion", `${window.innerHeight - borde}px`);
            } else {
                aviso.style.removeProperty("--aviso-operacion-separacion");
            }
        };
        const programarPosicion = () => {
            if (posicionPendiente || aviso.hidden) return;
            posicionPendiente = true;
            window.requestAnimationFrame(ubicar);
        };
        programarPosicion();
        window.addEventListener("load", programarPosicion, { once: true });
        window.addEventListener("resize", programarPosicion);
        window.addEventListener("scroll", programarPosicion, { passive: true });
        document.getElementById("sidebar-principal")?.addEventListener("toggle", programarPosicion, true);
        let temporizador;
        const cancelar = () => window.clearTimeout(temporizador);
        const ocultar = () => {
            if (aviso.hasAttribute("data-salida")) return;
            aviso.setAttribute("data-salida", "");
            cancelar();
            if (document.activeElement === cerrar) {
                document.getElementById("contenido-principal")?.focus({ preventScroll: true });
            }
            if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                aviso.hidden = true;
            } else {
                window.setTimeout(() => { aviso.hidden = true; }, 250);
            }
        };
        cerrar.addEventListener("click", ocultar);
        if (aviso.dataset.avisoOperacion === "exito") {
            const programar = () => {
                cancelar();
                if (!aviso.hidden && !aviso.hasAttribute("data-salida") && document.activeElement !== cerrar && !cerrar.matches(":hover")) {
                    temporizador = window.setTimeout(ocultar, 7000);
                }
            };
            cerrar.addEventListener("focus", cancelar);
            cerrar.addEventListener("pointerenter", cancelar);
            cerrar.addEventListener("blur", programar);
            cerrar.addEventListener("pointerleave", programar);
            programar();
        }
    }

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

    const movimientoReducido = window.matchMedia("(prefers-reduced-motion: reduce)");
    function animarIcono(control) {
        if (!control || movimientoReducido.matches || control.classList.contains("animando-icono")) return;
        control.classList.add("animando-icono");
        window.setTimeout(() => control.classList.remove("animando-icono"), 400);
    }
    const controlConIcono = (evento) => evento.target?.closest?.("[data-animar-icono]");
    document.addEventListener("pointerover", (evento) => {
        if (evento.pointerType === "touch") return;
        const control = controlConIcono(evento);
        if (control && !control.contains(evento.relatedTarget)) animarIcono(control);
    });
    document.addEventListener("focusin", (evento) => {
        const control = controlConIcono(evento);
        if (control?.matches(":focus-visible")) animarIcono(control);
    });
    document.addEventListener("pointerdown", (evento) => animarIcono(controlConIcono(evento)));
    document.addEventListener("click", (evento) => animarIcono(controlConIcono(evento)));
    document.addEventListener("animar-icono", (evento) => animarIcono(controlConIcono(evento)));
})();
