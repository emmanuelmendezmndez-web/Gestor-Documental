(() => {
    const dialogo = document.getElementById("busqueda-asistida");
    const abrir = document.getElementById("abrir-busqueda-asistida");
    const cerrar = document.getElementById("cerrar-busqueda-asistida");
    const frase = document.getElementById("frase-busqueda-asistida");
    const resumen = document.getElementById("filtros-sugeridos");
    const formulario = document.getElementById("form-busqueda-asistida");
    if (!dialogo || !abrir || !frase || !resumen || !formulario) return;

    const normalizar = texto => texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
    const categorias = window.sigedOpcionesBusqueda?.categorias || [];
    const areas = window.sigedOpcionesBusqueda?.areas || [];
    const areaUsuario = window.sigedOpcionesBusqueda?.areaUsuario || "";
    const areaRapida = window.sigedOpcionesBusqueda?.rol === "admin" ? "Obras Públicas" : areaUsuario;
    const botonArea = dialogo.querySelector('[data-busqueda-rapida="obras"]');
    if (botonArea) {
        botonArea.textContent = areaRapida ? `📁 ${areaRapida}` : "📁 Otros";
    }
    let busquedaRapida = null;
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
        const cuerpo = new Blob([JSON.stringify(datos)], { type: "application/json" });
        if (navigator.sendBeacon) navigator.sendBeacon("/asistente/habito", cuerpo);
        else fetch("/asistente/habito", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos), keepalive: true }).catch(() => {});
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
    const aliasCategorias = {
        contrato: "Contratos", contratos: "Contratos", oficio: null, oficios: null,
        acta: "Actas", actas: "Actas", certificado: "Certificados", certificados: "Certificados",
        informe: "Informes", informes: "Informes", bitacora: "Bitacoras", bitacoras: "Bitacoras",
        inventario: "Inventarios", inventarios: "Inventarios"
    };

    function interpretar(entrada) {
        const texto = normalizar(entrada.trim());
        const filtros = {};
        let restante = texto;
        const area = [...areas].sort((a, b) => b.length - a.length)
            .find(nombre => texto.includes(normalizar(nombre)));
        if (area) {
            filtros.departamento = area;
            restante = restante.replace(normalizar(area), " ");
        }
        const categoria = Object.entries(aliasCategorias).find(([palabra, valor]) =>
            valor && categorias.includes(valor) && new RegExp(`\\b${palabra}\\b`).test(texto));
        if (categoria) {
            filtros.categoria = categoria[1];
            restante = restante.replace(new RegExp(`\\b${categoria[0]}\\b`, "g"), " ");
        }
        const oficio = texto.match(/(?:oficio|of\.)\s*(?:numero|num\.?|no\.?)?\s*[:#-]?\s*([a-z]{0,8}[-\/]?\d+[\w\/-]*)/);
        if (oficio) {
            filtros.oficio = oficio[1];
            restante = restante.replace(oficio[0], " ");
        }
        const hoy = new Date();
        const anioExplicito = texto.match(/\b(?:20|19)\d{2}\b/);
        const mes = meses.findIndex(nombre => new RegExp(`\\b${nombre}\\b`).test(texto));
        const anio = anioExplicito ? Number(anioExplicito[0]) :
            /ano pasado/.test(texto) ? hoy.getFullYear() - 1 :
            /este ano/.test(texto) || mes >= 0 ? hoy.getFullYear() : null;
        if (anio && mes >= 0) {
            filtros.desde = `${anio}-${String(mes + 1).padStart(2, "0")}-01`;
            filtros.hasta = `${anio}-${String(mes + 1).padStart(2, "0")}-${String(new Date(anio, mes + 1, 0).getDate()).padStart(2, "0")}`;
        } else if (anio) {
            filtros.desde = `${anio}-01-01`;
            filtros.hasta = `${anio}-12-31`;
        }
        if (anioExplicito) restante = restante.replace(anioExplicito[0], " ");
        if (mes >= 0) restante = restante.replace(meses[mes], " ");
        restante = restante.replace(/\b(?:quiero|encontrar|buscar|busca|busco|muestrame|dame|necesito|los|las|el|la|un|una|unos|unas|de|del|en|por|para|sobre|que|se|registrado|registrada|registrados|registradas|este|ano|pasado|documento|documentos|archivo|archivos|oficio|oficios)\b/g, " ");
        const terminos = restante.replace(/[^\p{L}\p{N}\s-]/gu, " ").replace(/\s+/g, " ").trim();
        if (terminos) filtros.buscar = terminos.slice(0, 200);
        // Una frase genérica como "documento" también debe ejecutar la búsqueda.
        if (!Object.keys(filtros).length && texto) filtros.buscar = texto.slice(0, 200);
        return filtros;
    }

    function actualizar() {
        const filtros = busquedaRapida ? filtrosRapidos[busquedaRapida]() : interpretar(frase.value);
        const etiquetas = { buscar: "Texto", categoria: "Categoría", departamento: "Área", oficio: "Oficio", desde: "Desde", hasta: "Hasta" };
        resumen.hidden = !Object.entries(filtros).length;
        resumen.textContent = Object.entries(filtros).length
            ? "Filtros propuestos: " + Object.entries(filtros).map(([clave, valor]) => `${etiquetas[clave]}: ${valor}`).join(" · ")
            : "";
        return filtros;
    }
    abrir.addEventListener("click", () => { busquedaRapida = null; frase.value = ""; dialogo.showModal(); frase.focus(); actualizar(); });
    cerrar.addEventListener("click", () => dialogo.close());
    frase.addEventListener("input", () => { busquedaRapida = null; actualizar(); });
    dialogo.querySelectorAll("[data-busqueda-rapida]").forEach(boton => {
        boton.addEventListener("click", () => {
            busquedaRapida = boton.dataset.busquedaRapida;
            frase.value = boton.textContent.trim().replace(/^[^\p{L}]+/u, "");
            actualizar();
        });
    });
    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
        const filtros = actualizar();
        if (!Object.keys(filtros).length) {
            resumen.hidden = false;
            resumen.textContent = "Escribe qué documento buscas o elige una búsqueda rápida.";
            frase.focus();
            return;
        }
        guardarHabito({ tipo: "busqueda", filtros });
        window.location.assign("/?" + new URLSearchParams(filtros).toString());
    });
})();
