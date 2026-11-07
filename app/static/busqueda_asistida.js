(() => {
    const dialogo = document.getElementById("busqueda-asistida");
    const abrir = document.getElementById("abrir-busqueda-asistida");
    const cerrar = document.getElementById("cerrar-busqueda-asistida");
    const frase = document.getElementById("busqueda-global");
    const consultaTexto = document.getElementById("consulta-asistida-texto");
    const editarConsulta = document.getElementById("editar-consulta-asistida");
    const resumen = document.getElementById("filtros-sugeridos");
    const formulario = document.getElementById("form-busqueda-asistida");
    const reconocidos = document.getElementById("filtros-reconocidos");
    const adicionales = document.getElementById("filtros-adicionales");
    const agregar = document.getElementById("agregar-filtros");
    const sinReconocidos = document.getElementById("sin-filtros-reconocidos");
    const adicionalesActivos = document.getElementById("filtros-adicionales-activos");
    const claves = ["buscar", "categoria", "departamento", "oficio", "autor", "desde", "hasta"];
    const campos = Object.fromEntries(claves.map(clave => [clave, document.getElementById(`asistido-${clave}`)]));
    if (!dialogo || !abrir || !frase || !consultaTexto || !editarConsulta || !resumen || !formulario || !reconocidos || !adicionales || !agregar || !sinReconocidos || !adicionalesActivos || claves.some(clave => !campos[clave]) || typeof window.crearMemoriaTemporal !== "function") return;
    const grupos = Object.fromEntries(claves.map(clave => [clave, campos[clave].closest("[data-filtro]")]));
    if (claves.some(clave => !grupos[clave])) return;

    const categorias = window.sigedOpcionesBusqueda?.categorias || [];
    const areas = window.sigedOpcionesBusqueda?.areas || [];
    const areaUsuario = window.sigedOpcionesBusqueda?.areaUsuario || "";
    const areaRapida = window.sigedOpcionesBusqueda?.rol === "admin" ? "Obras Públicas" : areaUsuario;
    const botonArea = dialogo.querySelector('[data-busqueda-rapida="obras"]');
    if (botonArea) {
        botonArea.textContent = areaRapida ? `📁 ${areaRapida}` : "📁 Otros";
    }
    let busquedaRapida = null;
    let consulta = "";
    let interpretacion = null;
    let cambioPendiente = null;
    let editandoConsulta = false;
    const memoria = window.crearMemoriaTemporal();
    const editados = { has: clave => Boolean(memoria.consultar()?.manuales.includes(clave)) };
    const dudasPendientes = () => (interpretacion?.dudas || [])
        .map((duda, indice) => ({ duda, id: `duda_${indice}` }))
        .filter(item => memoria.consultar()?.pendientes.includes(item.id));
    const aclaracion = document.createElement("div");
    aclaracion.className = "consulta-asistida";
    aclaracion.setAttribute("role", "group");
    aclaracion.setAttribute("aria-label", "Aclaración de búsqueda");
    aclaracion.hidden = true;
    aclaracion.style.display = "none";
    resumen.after(aclaracion);
    const fechaLocal = fecha => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
    const ultimoMes = () => {
        const hoy = new Date();
        const desde = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - 30);
        return { desde: fechaLocal(desde), hasta: fechaLocal(hoy) };
    };
    const filtrosRapidos = {
        contratos: () => ({ categoria: "Contratos", ...ultimoMes() }),
        obras: () => areaRapida && areas.includes(areaRapida) ? { departamento: areaRapida } : { categoria: "Otros" },
        mes: ultimoMes
    };
    const guardarHabito = datos => {
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        if (!token) return;
        fetch("/asistente/habito", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": token }, body: JSON.stringify(datos), keepalive: true }).catch(() => {});
    };
    window.sigedClippyPreferencias = fetch(`/asistente/preferencias?hora=${new Date().getHours()}`, { credentials: "same-origin" })
        .then(respuesta => respuesta.ok ? respuesta.json() : null).catch(() => null);
    window.sigedClippyPreferencias.then(preferencias => {
        if (!preferencias?.busquedas?.length) return;
        const botones = [...dialogo.querySelectorAll("[data-busqueda-rapida]")];
        const vistas = new Set();
        preferencias.busquedas.filter(filtros => {
            const firma = JSON.stringify(Object.fromEntries(Object.entries(filtros)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([clave, valor]) => [clave, String(valor).toLocaleLowerCase("es")] )));
            if (vistas.has(firma)) return false;
            vistas.add(firma);
            return true;
        }).slice(0, 3).forEach((filtros, indice) => {
            const clave = `habitual${indice}`;
            filtrosRapidos[clave] = () => filtros;
            const resumen = filtros.buscar || filtros.oficio || filtros.categoria || filtros.departamento || "Búsqueda habitual";
            botones[indice].textContent = `✦ ${resumen.slice(0, 28)}`;
            botones[indice].dataset.busquedaRapida = clave;
            botones[indice].title = "Usar filtros de una búsqueda habitual";
        });
    });

    document.addEventListener("submit", evento => {
        const form = evento.target;
        if (!(form instanceof HTMLFormElement) || form === formulario || form.method.toLowerCase() !== "get") return;
        const ruta = new URL(form.action).pathname;
        if (ruta !== "/" && ruta !== "/buscar") return;
        const datos = new FormData(form);
        const filtros = ruta === "/buscar" ? { buscar: String(datos.get("q") || "").trim() } :
            Object.fromEntries(["buscar", "categoria", "departamento", "oficio", "desde", "hasta"]
                .map(clave => [clave, String(datos.get(clave) || "").trim()]).filter(([, valor]) => valor));
        if (Object.keys(filtros).length) guardarHabito({ tipo: "busqueda", filtros });
    });
    const seccion = window.location.pathname.split("/")[1] || "biblioteca";
    const claveSeccion = `siged-clippy-${window.sigedOpcionesBusqueda.usuarioId}-${seccion}`;
    if (!sessionStorage.getItem(claveSeccion)) {
        sessionStorage.setItem(claveSeccion, "1");
        guardarHabito({ tipo: "seccion", valor: seccion });
        guardarHabito({ tipo: "rutina", valor: seccion, hora: new Date().getHours() });
    }
    const expedienteVisitado = window.location.pathname.match(/^\/expedientes\/(\d+)$/);
    if (expedienteVisitado) guardarHabito({ tipo: "expediente", valor: expedienteVisitado[1] });
    function mostrarOrigen(clave) {
        const nota = dialogo.querySelector(`[data-origen="${clave}"]`);
        if (nota) nota.textContent = editados.has(clave) ? "Modificado por ti" : !campos[clave].value ? "Sin aplicar" :
            busquedaRapida || clave === "desde" || clave === "hasta" ? "Inferido por reglas; revisa" : "Detectado en la consulta por reglas; revisa";
    }
    function contarAdicionales() {
        const cantidad = claves.filter(clave => grupos[clave].parentElement === adicionales && campos[clave].value.trim()).length;
        adicionalesActivos.textContent = cantidad ? `(${cantidad} ${cantidad === 1 ? "activo" : "activos"})` : "";
    }
    function actualizar() {
        interpretacion = busquedaRapida ? null : window.sigedInterpretarBusqueda.detallar(consulta, categorias, areas);
        const filtros = busquedaRapida ? filtrosRapidos[busquedaRapida]() : interpretacion.filtros;
        if (memoria.consultar()) memoria.reiniciar();
        memoria.iniciar(frase.value, interpretacion?.expediente ? "expedientes" : "documentos", filtros);
        (interpretacion?.dudas || []).forEach((duda, indice) => memoria.pendiente(`duda_${indice}`));
        consultaTexto.textContent = consulta || "Sin consulta escrita";
        for (const clave of claves) {
            campos[clave].value = memoria.consultar().filtros[clave] || "";
            (filtros[clave] ? reconocidos : adicionales).appendChild(grupos[clave]);
            mostrarOrigen(clave);
        }
        sinReconocidos.hidden = reconocidos.childElementCount > 0;
        contarAdicionales();
        mostrarAvisos();
    }
    function mostrarAvisos(mensaje = "") {
        const avisos = [...(mensaje ? [mensaje] : []), ...(dudasPendientes().length ? ["Clippy encontró criterios que necesitan aclaración."] : [])];
        resumen.textContent = avisos.join(" ");
        if (interpretacion?.expediente) {
            const enlace = document.createElement("a");
            enlace.href = "/buscar?" + new URLSearchParams({q: interpretacion.expediente}).toString();
            enlace.textContent = `Buscar expediente ${interpretacion.expediente} en búsqueda global`;
            resumen.append(" ", enlace);
        }
        resumen.hidden = !avisos.length && !interpretacion?.expediente;
        mostrarAclaracion();
    }
    function mostrarAclaracion(mensaje = "") {
        aclaracion.replaceChildren();
        const pendiente = dudasPendientes()[0];
        const duda = pendiente?.duda;
        aclaracion.hidden = !duda;
        aclaracion.style.display = duda ? "" : "none";
        if (!duda) return;
        const pregunta = document.createElement("p");
        const opciones = [];
        const agregarOpcion = (etiqueta, filtros, accion = "aplicar") => opciones.push({etiqueta, filtros, accion});
        const fechaLocalSegura = (anio, parte, final = false) => {
            const d = final && parte.dia === null ? new Date(anio, parte.mes + 1, 0) : new Date(anio, parte.mes, parte.dia);
            return d.getFullYear() === anio && d.getMonth() === parte.mes ? fechaLocal(d) : null;
        };
        if (duda.tipo === "mes_sin_anio" || duda.tipo === "rango_sin_anio") {
            pregunta.textContent = duda.tipo === "mes_sin_anio" ? `¿De qué año es ${duda.nombre}?` : "¿De qué año es el intervalo?";
            const anio = new Date().getFullYear();
            for (const valor of [anio, anio - 1]) {
                const inicio = duda.inicio || {mes:duda.mes, dia:1};
                const fin = duda.fin || {mes:duda.mes, dia:null};
                const desde = fechaLocalSegura(valor, inicio), hasta = fechaLocalSegura(valor, fin, true);
                if (desde && hasta && desde <= hasta) agregarOpcion(String(valor), {desde, hasta});
            }
            agregarOpcion("Otro año o intervalo", {}, "fechas");
        } else if (duda.tipo === "fecha_numerica" || duda.tipo === "fechas_multiples") {
            pregunta.textContent = duda.tipo === "fecha_numerica" ? "¿Qué fecha quisiste indicar?" : "Biblioteca solo admite un intervalo. ¿Cuál deseas aplicar?";
            for (const opcion of duda.opciones) {
                const filtros = typeof opcion === "string" ? {desde:opcion, hasta:opcion} : opcion;
                agregarOpcion(filtros.desde === filtros.hasta ? filtros.desde : `${filtros.desde} a ${filtros.hasta}`, filtros);
            }
            agregarOpcion("Editar fechas", {}, "fechas");
        } else if (duda.tipo === "categoria" || duda.tipo === "area") {
            const clave = duda.tipo === "categoria" ? "categoria" : "departamento";
            pregunta.textContent = duda.tipo === "categoria" ? "Biblioteca solo admite una categoría. ¿Cuál deseas usar?" : "¿Qué departamento deseas usar?";
            for (const valor of duda.opciones) agregarOpcion(valor, {[clave]:valor});
        } else if (duda.tipo === "obras") {
            pregunta.textContent = "¿“Obras” es un tema o el departamento de Obras Públicas?";
            agregarOpcion("Tema documental", {}, "tema");
            agregarOpcion("Departamento Obras Públicas", {departamento:duda.area}, "area_obras");
        } else {
            pregunta.textContent = "El intervalo es incompleto o inválido. Puedes indicar las fechas manualmente.";
            agregarOpcion("Editar fechas", {}, "fechas");
        }
        if (mensaje) pregunta.textContent += ` ${mensaje}`;
        aclaracion.append(pregunta);
        for (const [indice, opcion] of opciones.entries()) {
            const boton = document.createElement("button");
            boton.type = "button"; boton.className = "boton-secundario"; boton.textContent = opcion.etiqueta;
            boton.addEventListener("click", () => {
                const clavesOpcion = Object.keys(opcion.filtros);
                if (clavesOpcion.some(clave => editados.has(clave))) {
                    mostrarAclaracion("Se conservaron tus filtros editados; ajústalos manualmente si lo deseas.");
                    aclaracion.querySelector?.("button")?.focus();
                    return;
                }
                if (opcion.accion === "fechas") {
                    agregar.open = true; grupos.desde.parentElement === adicionales && agregar.scrollIntoView?.({block:"nearest"});
                    campos.desde.focus();
                }
                const cambios = {...opcion.filtros};
                if (opcion.accion === "area_obras" && !editados.has("buscar")) {
                    cambios.buscar = (memoria.consultar().filtros.buscar || "").replace(/\bobras\b/i, " ").replace(/\s+/g, " ").trim();
                }
                memoria.resolver(pendiente.id, `opcion_${indice}`, cambios);
                for (const clave of clavesOpcion) memoria.marcarManual(clave);
                const guardados = memoria.consultar().filtros;
                for (const clave of Object.keys(cambios)) {
                    campos[clave].value = guardados[clave] || "";
                    reconocidos.appendChild(grupos[clave]); mostrarOrigen(clave);
                }
                sinReconocidos.hidden = reconocidos.childElementCount > 0;
                contarAdicionales(); mostrarAvisos();
                if (opcion.accion !== "fechas") (aclaracion.querySelector?.("button") || editarConsulta).focus();
            });
            aclaracion.append(boton);
        }
        const omitir = document.createElement("button");
        omitir.type = "button"; omitir.className = "boton-secundario"; omitir.textContent = "Dejar sin aplicar";
        omitir.addEventListener("click", () => {
            const cambios = duda.tipo === "obras" && !editados.has("buscar") ? {
                buscar: (memoria.consultar().filtros.buscar || "").replace(/\bobras\b/i, " ").replace(/\s+/g, " ").trim()
            } : {};
            memoria.resolver(pendiente.id, "omitir", cambios);
            if (Object.hasOwn(cambios, "buscar")) { campos.buscar.value = memoria.consultar().filtros.buscar || ""; mostrarOrigen("buscar"); }
            mostrarAvisos();
            (aclaracion.querySelector?.("button") || editarConsulta).focus();
        });
        aclaracion.append(omitir);
    }
    function sincronizarEdicion(clave) {
        if (!memoria.consultar()) return;
        memoria.marcarManual(clave);
        const cambios = Object.fromEntries(memoria.consultar().manuales.map(nombre => [nombre, campos[nombre].value.trim()]));
        // Mientras se escribe una fecha inválida, el DOM mantiene el borrador y
        // la memoria conserva el último conjunto válido de filtros.
        try { memoria.actualizar(cambios); } catch (error) {
            if (!(error instanceof RangeError || error instanceof TypeError)) throw error;
        }
        mostrarOrigen(clave); contarAdicionales();
    }
    for (const clave of claves) {
        campos[clave].addEventListener("input", () => sincronizarEdicion(clave));
        campos[clave].addEventListener("change", () => sincronizarEdicion(clave));
    }
    function borrarInteraccion() {
        memoria.cancelar();
        editandoConsulta = false;
        busquedaRapida = null; consulta = ""; interpretacion = null; cambioPendiente = null;
        for (const clave of claves) campos[clave].value = "";
        consultaTexto.textContent = ""; resumen.textContent = ""; resumen.hidden = true;
        aclaracion.replaceChildren(); aclaracion.hidden = true; aclaracion.style.display = "none";
        adicionalesActivos.textContent = "";
    }
    function mostrarCambio() {
        resumen.hidden = false;
        resumen.textContent = "Cambiar la consulta iniciará una búsqueda nueva y descartará los filtros editados de esta interacción.";
        aclaracion.replaceChildren(); aclaracion.hidden = false; aclaracion.style.display = "";
        const pregunta = document.createElement("p");
        pregunta.textContent = "¿Deseas continuar o volver a la consulta anterior con sus filtros?";
        aclaracion.append(pregunta);
        const continuar = document.createElement("button");
        continuar.type = "button"; continuar.className = "boton-secundario"; continuar.textContent = "Iniciar búsqueda nueva";
        continuar.addEventListener("click", () => {
            const siguiente = cambioPendiente; cambioPendiente = null;
            busquedaRapida = siguiente.rapida; consulta = siguiente.consulta;
            actualizar(); editarConsulta.focus();
        });
        const volver = document.createElement("button");
        volver.type = "button"; volver.className = "boton-secundario"; volver.textContent = "Volver a consulta anterior";
        volver.addEventListener("click", () => {
            frase.value = memoria.consultar().consulta; cambioPendiente = null;
            mostrarAvisos(); editarConsulta.focus();
        });
        aclaracion.append(continuar, volver); continuar.focus();
    }
    abrir.addEventListener("click", () => {
        // El evento close del navegador puede llegar después de una reapertura.
        // Solo la transición explícita de edición conserva la interacción.
        if (memoria.consultar() && !dialogo.open && !editandoConsulta) borrarInteraccion();
        editandoConsulta = false;
        const estado = memoria.consultar();
        if (!estado) { busquedaRapida = null; consulta = frase.value; actualizar(); }
        else if (estado.consulta !== frase.value) {
            if (estado.manuales.length) cambioPendiente = {rapida: null, consulta: frase.value};
            else { busquedaRapida = null; consulta = frase.value; actualizar(); }
        }
        dialogo.showModal();
        if (cambioPendiente) mostrarCambio(); else editarConsulta.focus();
    });
    cerrar.addEventListener("click", () => { borrarInteraccion(); dialogo.close(); });
    editarConsulta.addEventListener("click", () => { editandoConsulta = true; dialogo.close(); frase.focus(); });
    dialogo.addEventListener("cancel", borrarInteraccion);
    dialogo.addEventListener("close", () => {
        if (dialogo.open || editandoConsulta) return;
        borrarInteraccion();
    });
    window.addEventListener("pagehide", borrarInteraccion);
    dialogo.querySelectorAll("[data-busqueda-rapida]").forEach(boton => {
        boton.addEventListener("click", () => {
            const siguiente = {rapida: boton.dataset.busquedaRapida, consulta: boton.textContent.trim().replace(/^[^\p{L}]+/u, "")};
            if (memoria.consultar()?.manuales.length) { cambioPendiente = siguiente; mostrarCambio(); return; }
            busquedaRapida = siguiente.rapida; consulta = siguiente.consulta; actualizar();
        });
    });
    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
        if (cambioPendiente) { mostrarCambio(); return; }
        if (dudasPendientes().length) {
            mostrarAvisos("Resuelve la aclaración o elige dejarla sin aplicar antes de buscar.");
            aclaracion.querySelector?.("button")?.focus();
            return;
        }
        if (!formulario.checkValidity()) { agregar.open = true; formulario.reportValidity(); return; }
        const filtros = Object.fromEntries(claves.map(clave => [clave, campos[clave].value.trim()]).filter(([, valor]) => valor));
        for (const clave of ["desde", "hasta"]) {
            if (filtros[clave] && !/^\d{4}-\d{2}-\d{2}$/.test(filtros[clave])) {
                resumen.hidden = false;
                resumen.textContent = "Escribe una fecha válida con año de cuatro cifras.";
                if (grupos[clave].parentElement === adicionales) agregar.open = true;
                campos[clave].focus();
                return;
            }
        }
        if (filtros.desde && filtros.hasta && filtros.desde > filtros.hasta) {
            resumen.hidden = false;
            resumen.textContent = "La fecha inicial no puede ser posterior a la fecha final.";
            if (grupos.desde.parentElement === adicionales) agregar.open = true;
            campos.desde.focus();
            return;
        }
        if (!Object.keys(filtros).length) {
            mostrarAvisos("Escribe qué documento buscas o elige una búsqueda rápida.");
            editarConsulta.focus();
            return;
        }
        const cambiosManuales = Object.fromEntries(memoria.consultar().manuales.map(clave => [clave, campos[clave].value.trim()]));
        memoria.actualizar(cambiosManuales);
        const confirmados = memoria.consultar().filtros;
        const destino = "/?" + new URLSearchParams(confirmados).toString();
        guardarHabito({ tipo: "busqueda", filtros: confirmados });
        memoria.finalizar();
        borrarInteraccion();
        window.location.assign(destino);
    });
})();
