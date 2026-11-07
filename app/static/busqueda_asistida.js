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
    if (!dialogo || !abrir || !frase || !consultaTexto || !editarConsulta || !resumen || !formulario || !reconocidos || !adicionales || !agregar || !sinReconocidos || !adicionalesActivos || claves.some(clave => !campos[clave])) return;
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
    let ultimaFrase = null;
    let interpretacion = null;
    const editados = new Set();
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
    function actualizar(conservarEditados = false) {
        interpretacion = busquedaRapida ? null : window.sigedInterpretarBusqueda.detallar(consulta, categorias, areas);
        const filtros = busquedaRapida ? filtrosRapidos[busquedaRapida]() : interpretacion.filtros;
        consultaTexto.textContent = consulta || "Sin consulta escrita";
        for (const clave of claves) {
            if (!conservarEditados || !editados.has(clave)) campos[clave].value = filtros[clave] || "";
            (filtros[clave] ? reconocidos : adicionales).appendChild(grupos[clave]);
            mostrarOrigen(clave);
        }
        sinReconocidos.hidden = reconocidos.childElementCount > 0;
        contarAdicionales();
        mostrarAvisos();
    }
    function mostrarAvisos(mensaje = "") {
        const avisos = [...(mensaje ? [mensaje] : []), ...(interpretacion?.avisos || [])];
        resumen.textContent = avisos.join(" ");
        if (interpretacion?.expediente) {
            const enlace = document.createElement("a");
            enlace.href = "/buscar?" + new URLSearchParams({q: interpretacion.expediente}).toString();
            enlace.textContent = `Buscar expediente ${interpretacion.expediente} en búsqueda global`;
            resumen.append(" ", enlace);
        }
        resumen.hidden = !avisos.length && !interpretacion?.expediente;
    }
    for (const clave of claves) {
        campos[clave].addEventListener("input", () => { editados.add(clave); mostrarOrigen(clave); contarAdicionales(); });
        campos[clave].addEventListener("change", () => { editados.add(clave); mostrarOrigen(clave); contarAdicionales(); });
    }
    abrir.addEventListener("click", () => {
        if (ultimaFrase !== frase.value) {
            busquedaRapida = null;
            consulta = frase.value;
            actualizar(ultimaFrase !== null);
            ultimaFrase = frase.value;
        }
        dialogo.showModal();
        editarConsulta.focus();
    });
    cerrar.addEventListener("click", () => dialogo.close());
    editarConsulta.addEventListener("click", () => { dialogo.close(); frase.focus(); });
    dialogo.querySelectorAll("[data-busqueda-rapida]").forEach(boton => {
        boton.addEventListener("click", () => {
            busquedaRapida = boton.dataset.busquedaRapida;
            consulta = boton.textContent.trim().replace(/^[^\p{L}]+/u, "");
            editados.clear();
            actualizar();
        });
    });
    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
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
        guardarHabito({ tipo: "busqueda", filtros });
        window.location.assign("/?" + new URLSearchParams(filtros).toString());
    });
})();
