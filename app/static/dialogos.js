(() => {
    const dialogo = document.getElementById("dialogo-confirmacion");
    if (!dialogo) return;
    const titulo = document.getElementById("dialogo-confirmacion-titulo");
    const mensaje = document.getElementById("dialogo-confirmacion-mensaje");
    const afectado = document.getElementById("dialogo-confirmacion-afectado");
    const nombreAfectado = document.getElementById("dialogo-confirmacion-afectado-nombre");
    const iconoAfectado = document.getElementById("dialogo-confirmacion-afectado-icono");
    const botonConfirmar = dialogo.querySelector("[data-dialogo-confirmar]");
    const botonCancelar = dialogo.querySelector("[data-dialogo-cancelar]");
    const campoClaveContenedor = document.getElementById("dialogo-clave-confirmacion");
    const campoClave = document.getElementById("dialogo-confirmacion-password");
    let formularioPendiente = null;
    let botonPendiente = null;
    let origenConfirmacion = null;
    let soloAviso = false;
    let cerrandoDialogo = false;

    function limpiarClaveConfirmacion() {
        campoClave.value = "";
        campoClave.disabled = true;
        campoClave.setCustomValidity("");
        campoClaveContenedor.hidden = true;
    }

    // Resalta únicamente el fragmento ya delimitado en el mensaje, sin HTML dinámico.
    function mostrarMensaje(texto) {
        const inicio = texto.indexOf("«"), fin = texto.indexOf("»", inicio + 1);
        if (inicio < 0 || fin <= inicio + 1) { mensaje.textContent = texto; return ""; }
        const nombre = document.createElement("strong");
        nombre.textContent = texto.slice(inicio, fin + 1);
        mensaje.replaceChildren(document.createTextNode(texto.slice(0, inicio)), nombre,
            document.createTextNode(texto.slice(fin + 1)));
        return texto.slice(inicio + 1, fin);
    }

    function iconoOperacion(ruta, origen) {
        if (origen.dataset.confirmPassword === "true") return "administracion";
        if (ruta === "/papelera/restaurar" || /^\/documentos\/\d+\/restaurar$/.test(ruta)) return "restaurar";
        if (ruta === "/documentos/papelera" || /^\/documentos\/\d+\/eliminar$/.test(ruta)) return "enviar-papelera";
        if (ruta.startsWith("/documentos/")) return "documento";
        if (ruta.startsWith("/expedientes/")) return "expediente";
        if (ruta.startsWith("/papelera/")) return "papelera";
        if (ruta.startsWith("/usuarios/")) return "usuario";
        if (ruta.startsWith("/avisos/")) return "comunicado";
        return "aviso";
    }

    function cerrarDialogo(alTerminar) {
        if (!dialogo.open) {
            alTerminar?.();
            return;
        }
        if (cerrandoDialogo) return;
        cerrandoDialogo = true;
        dialogo.classList.add("dialogo-cerrando");
        let finalizada = false;
        let respaldoCierre = null;
        const finalizar = (evento) => {
            if (evento && evento.target !== dialogo) return;
            if (finalizada) return;
            finalizada = true;
            dialogo.removeEventListener("animationend", finalizar);
            if (respaldoCierre !== null) window.clearTimeout(respaldoCierre);
            dialogo.classList.remove("dialogo-cerrando");
            cerrandoDialogo = false;
            dialogo.close();
            alTerminar?.();
        };
        dialogo.addEventListener("animationend", finalizar);
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            finalizar();
        } else {
            respaldoCierre = window.setTimeout(() => finalizar(), 220);
        }
    }

    document.addEventListener("submit", (evento) => {
        const formulario = evento.target;
        const boton = evento.submitter;
        if (formulario?.dataset.requiredSelection) {
            const nombre = formulario.dataset.requiredSelection;
            const haySeleccion = Array.from(formulario.elements).some((control) =>
                control.type === "checkbox" && control.name === nombre && control.checked
            );
            if (!haySeleccion) {
                evento.preventDefault();
                soloAviso = true;
                dialogo.dataset.tono = "aviso";
                dialogo.dataset.icono = "aviso";
                afectado.hidden = true;
                nombreAfectado.textContent = "";
                iconoAfectado.replaceChildren();
                botonConfirmar.classList.remove("boton-peligro");
                botonCancelar.hidden = true;
                titulo.textContent = "Selecciona documentos";
                mensaje.textContent = "Selecciona al menos un documento para continuar.";
                botonConfirmar.textContent = "Entendido";
                dialogo.showModal();
                return;
            }
        }
        const origen = boton?.hasAttribute("data-confirm") ? boton : formulario;
        if (!origen?.hasAttribute("data-confirm")) return;
        if (origen.dataset.confirmado === "true") {
            delete origen.dataset.confirmado;
            return;
        }

        evento.preventDefault();
        soloAviso = false;
        botonCancelar.hidden = false;
        formularioPendiente = formulario;
        botonPendiente = boton;
        origenConfirmacion = origen;
        const ruta = boton?.getAttribute("formaction") || formulario.getAttribute("action") || "";
        const reversible = ruta === "/documentos/papelera" || /^\/documentos\/\d+\/eliminar$/.test(ruta) || ruta === "/papelera/restaurar" || /^\/documentos\/\d+\/restaurar$/.test(ruta);
        dialogo.dataset.tono = reversible ? "aviso" : origen.dataset.confirmTone === "danger" ? "peligro" : "normal";
        dialogo.dataset.icono = iconoOperacion(ruta, origen);
        titulo.textContent = origen.dataset.confirmTitle || "Confirma esta acción";
        const nombreEnMensaje = mostrarMensaje(origen.dataset.confirm || "¿Deseas continuar?");
        const nombre = origen.dataset.confirmSubject || nombreEnMensaje;
        if (nombre && origen.dataset.confirmDescription) mensaje.textContent = origen.dataset.confirmDescription;
        nombreAfectado.textContent = nombre;
        const plantillaIcono = origen.querySelector("template[data-confirm-file-icon]");
        iconoAfectado.replaceChildren(...(nombre && plantillaIcono ? [plantillaIcono.content.cloneNode(true)] : []));
        afectado.hidden = !nombre;
        botonConfirmar.textContent = origen.dataset.confirmLabel || "Continuar";
        botonConfirmar.classList.toggle("boton-peligro", origen.dataset.confirmTone === "danger");
        const requiereClave = origen.dataset.confirmPassword === "true";
        campoClaveContenedor.hidden = !requiereClave;
        campoClave.disabled = !requiereClave;
        campoClave.value = "";
        campoClave.setCustomValidity("");
        dialogo.showModal();
        if (requiereClave) window.requestAnimationFrame(() => campoClave.focus());
    });

    campoClave.addEventListener("input", () => campoClave.setCustomValidity(""));
    botonCancelar.addEventListener("click", () => {
        limpiarClaveConfirmacion();
        cerrarDialogo();
    });
    botonConfirmar.addEventListener("click", () => {
        if (cerrandoDialogo || !dialogo.open) return;
        if (soloAviso) {
            cerrarDialogo();
            return;
        }
        if (!formularioPendiente) return;
        const formulario = formularioPendiente;
        const boton = botonPendiente;
        const origen = origenConfirmacion;
        if (formulario.dataset.confirmPassword === "true") {
            if (!campoClave.value) {
                campoClave.setCustomValidity("Escribe tu contraseña actual para continuar.");
                campoClave.reportValidity();
                campoClave.focus();
                return;
            }
            let campoOculto = formulario.querySelector("[data-confirm-password-value]");
            if (!campoOculto) {
                campoOculto = document.createElement("input");
                campoOculto.type = "hidden";
                campoOculto.name = "password";
                campoOculto.dataset.confirmPasswordValue = "true";
                formulario.append(campoOculto);
            }
            campoOculto.value = campoClave.value;
            limpiarClaveConfirmacion();
        }
        dialogo.close();
        origen.dataset.confirmado = "true";
        if (boton && boton.form === formulario) formulario.requestSubmit(boton);
        else formulario.requestSubmit();
    });

    dialogo.addEventListener("cancel", (evento) => {
        evento.preventDefault();
        cerrarDialogo();
    });
    dialogo.addEventListener("click", (evento) => {
        if (evento.target === dialogo) cerrarDialogo();
    });

    dialogo.addEventListener("close", () => {
        // El evento puede llegar después de haber abierto otra confirmación.
        if (dialogo.open) return;
        cerrandoDialogo = false;
        soloAviso = false;
        limpiarClaveConfirmacion();
        botonCancelar.hidden = false;
        formularioPendiente = null;
        botonPendiente = null;
        origenConfirmacion = null;
    });

    function sincronizarSeleccion(formulario) {
        if (!formulario?.dataset.requiredSelection) return;
        const nombre = formulario.dataset.requiredSelection;
        const casillas = Array.from(formulario.elements).filter((control) =>
            control.type === "checkbox" && control.name === nombre
        );
        const seleccionados = casillas.filter((control) => control.checked).length;
        const seleccionarTodos = formulario.querySelector("[data-select-all]");
        if (seleccionarTodos) {
            seleccionarTodos.checked = casillas.length > 0 && seleccionados === casillas.length;
            seleccionarTodos.indeterminate = seleccionados > 0 && seleccionados < casillas.length;
        }
        formulario.querySelectorAll('[data-requires-selection="' + nombre + '"]').forEach((boton) => {
            boton.disabled = seleccionados === 0;
            boton.setAttribute("aria-disabled", String(seleccionados === 0));
        });
    }

    document.addEventListener("change", (evento) => {
        const control = evento.target;
        if (!(control instanceof HTMLInputElement)) return;
        if (control.matches("[data-select-all]")) {
            const formulario = control.form;
            if (!formulario) return;
            Array.from(formulario.elements)
                .filter((casilla) => casilla.classList.contains(control.dataset.selectAll))
                .forEach((casilla) => {
                    casilla.checked = control.checked;
                });
            sincronizarSeleccion(formulario);
        } else if (control.type === "checkbox" && control.name === "documento_ids") {
            sincronizarSeleccion(control.form);
        }
    });
    document.querySelectorAll("form[data-required-selection]").forEach(sincronizarSeleccion);

})();
