(() => {
    const dialogo = document.getElementById("busqueda-asistida");
    const abrir = document.getElementById("abrir-busqueda-asistida");
    const cerrar = document.getElementById("cerrar-busqueda-asistida");
    const frase = document.getElementById("busqueda-global");
    const consultaTexto = document.getElementById("consulta-asistida-texto");
    const editarConsulta = document.getElementById("editar-consulta-asistida");
    const resumen = document.getElementById("filtros-sugeridos");
    const formulario = document.getElementById("form-busqueda-asistida");
    if (!dialogo || !abrir || !frase || !consultaTexto || !editarConsulta || !resumen || !formulario) return;

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
    function actualizar() {
        const filtros = busquedaRapida ? filtrosRapidos[busquedaRapida]() : window.sigedInterpretarBusqueda(consulta, categorias, areas);
        consultaTexto.textContent = consulta || "Sin consulta escrita";
        const etiquetas = { buscar: "Texto", categoria: "Categoría", departamento: "Área", oficio: "Oficio", desde: "Desde", hasta: "Hasta" };
        resumen.hidden = !Object.entries(filtros).length;
        resumen.textContent = Object.entries(filtros).length
            ? "Filtros propuestos: " + Object.entries(filtros).map(([clave, valor]) => `${etiquetas[clave]}: ${valor}`).join(" · ")
            : "";
        return filtros;
    }
    abrir.addEventListener("click", () => { busquedaRapida = null; consulta = frase.value; actualizar(); dialogo.showModal(); editarConsulta.focus(); });
    cerrar.addEventListener("click", () => dialogo.close());
    editarConsulta.addEventListener("click", () => { dialogo.close(); frase.focus(); });
    dialogo.querySelectorAll("[data-busqueda-rapida]").forEach(boton => {
        boton.addEventListener("click", () => {
            busquedaRapida = boton.dataset.busquedaRapida;
            consulta = boton.textContent.trim().replace(/^[^\p{L}]+/u, "");
            actualizar();
        });
    });
    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
        const filtros = actualizar();
        if (!Object.keys(filtros).length) {
            resumen.hidden = false;
            resumen.textContent = "Escribe qué documento buscas o elige una búsqueda rápida.";
            editarConsulta.focus();
            return;
        }
        guardarHabito({ tipo: "busqueda", filtros });
        window.location.assign("/?" + new URLSearchParams(filtros).toString());
    });
})();
