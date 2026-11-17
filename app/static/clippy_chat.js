(() => {
    const dialogo = document.getElementById("chat-clippy");
    const abrir = document.getElementById("abrir-chat-clippy");
    if (!dialogo || !abrir) return;
    const historial = dialogo.querySelector("[data-chat-historial]");
    const irAlFinal = dialogo.querySelector("[data-chat-ir-final]");
    const inicio = dialogo.querySelector("[data-chat-inicio]");
    const actividad = dialogo.querySelector("[data-chat-actividad]");
    const progreso = dialogo.querySelector("[data-chat-estado]");
    const modelo = dialogo.querySelector("[data-chat-modelo]");
    const mensajesModelo = Object.freeze({
        cargando: "Preparando MiniLM… Por ahora, Clippy puede responder con capacidades reducidas.",
        listo: "MiniLM listo.",
        no_disponible: "MiniLM no está disponible. Clippy puede seguir ayudando con sus reglas locales.",
        reglas: "Clippy utiliza reglas locales en esta sesión.",
        sin_conexion: "No se pudo consultar el estado de MiniLM."
    });
    let sondeoModelo;
    let consultaModelo;
    const formulario = dialogo.querySelector("form");
    const campo = formulario.elements.texto;
    const enviar = formulario.querySelector("button");
    const opciones = window.sigedOpcionesBusqueda || {};
    const config = window.sigedClippyConfig || {};
    const resolver = window.sigedPlanClippy.resolver;
    const capacidades = {ver:config.puedeVer, ver_expedientes:config.puedeVerExpedientes,
        gestionar_expedientes:config.puedeGestionarExpedientes, subir:config.puedeSubir, usuarios:config.puedeUsuarios,
        actividad:config.puedeActividad, papelera:config.puedePapelera, restaurar:config.puedeRestaurar,
        eliminar:config.puedeEliminar, editar:config.puedeEditar, descargar:config.puedeDescargar, avisos:config.puedeAvisos};
    const pagina = dialogo.dataset.pagina;
    const ayuda = tema => window.sigedConsultarAyuda(tema,{pantalla:pagina,capacidades});
    const opts = {categorias:opciones.categorias || [], areas:opciones.areas || [],
        detallar:window.sigedInterpretarBusqueda.detallar,
        contextual:window.sigedInterpretarContexto, clasificar:window.sigedClasificarAyuda,
        ayudaValida:tema=>typeof tema==="string" && ayuda(tema)!==ayuda("")};
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    let filtros = null;
    let pendientes = null;
    let pideRegistro = false;
    let activo;
    let reloj;
    let estadoActual;
    function elemento(tag, clase, texto) {
        const nodo = document.createElement(tag);
        if (clase) nodo.className=clase;
        if (texto) nodo.textContent=texto;
        return nodo;
    }
    let sigueFinal = true;
    function actualizarDesplazamiento() {
        const distancia = historial.scrollHeight - historial.clientHeight - historial.scrollTop;
        sigueFinal = distancia <= 24;
        irAlFinal.hidden = sigueFinal;
    }
    function mantenerPosicion() {
        if (sigueFinal) historial.scrollTop = historial.scrollHeight;
        actualizarDesplazamiento();
    }
    historial.addEventListener("scroll", actualizarDesplazamiento, {passive: true});
    new ResizeObserver(mantenerPosicion).observe(historial);
    irAlFinal.addEventListener("click", () => {
        sigueFinal = true;
        historial.focus({preventScroll: true});
        mantenerPosicion();
    });
    function turno(texto, usuario = false, conTarjetas = false) {
        historial.querySelector(".chat-inicio")?.remove();
        const clase = usuario ? " chat-turno-usuario" : " chat-turno-asistente";
        const fila = elemento("article", "chat-turno" + clase);
        const contenido = elemento("div", "chat-turno-contenido" + (conTarjetas ? " chat-turno-resultados" : ""));
        if (!usuario) {
            const avatar = elemento("span", "chat-avatar");
            avatar.setAttribute("aria-hidden", "true");
            fila.append(avatar);
        }
        contenido.append(elemento("span", "chat-solo-lectores", usuario ? "Tú" : "Clippy IA"), elemento("p", "", texto));
        fila.append(contenido);
        historial.append(fila);
        mantenerPosicion();
        return contenido;
    }
    function etapa(trabajo, texto) {
        estadoActual = texto;
        if (!actividad.hidden) {
            progreso.textContent = estadoActual;
            return;
        }
        if (reloj !== undefined) return;
        // Las etapas rápidas se resuelven sin interrumpir la lectura con un indicador.
        reloj = setTimeout(() => {
            if (activo !== trabajo) return;
            actividad.hidden = false;
            progreso.textContent = estadoActual;
        }, 160);
    }
    function terminar(trabajo) {
        if (activo !== trabajo) return;
        clearTimeout(reloj);
        reloj = undefined;
        progreso.textContent = "";
        actividad.hidden = true;
        activo = null;
        enviar.disabled = false;
        formulario.removeAttribute("aria-busy");
    }
    function reiniciar() {
        if (activo) { activo.abort(); terminar(activo); }
        filtros = null;
        pendientes = null;
        pideRegistro = false;
        historial.replaceChildren(inicio.content.cloneNode(true));
        sigueFinal = true;
        mantenerPosicion();
    }
    function icono(nombre) {
        const i = elemento("i", "ph-bold ph-" + nombre);
        i.setAttribute("aria-hidden", "true");
        return i;
    }
    function tipoArchivo(extension) {
        return {
            ".pdf": ["file-pdf", "pdf"], ".doc": ["file-doc", "texto"], ".docx": ["file-doc", "texto"],
            ".xls": ["file-xls", "hoja"], ".xlsx": ["file-xls", "hoja"], ".csv": ["file-csv", "hoja"],
            ".png": ["file-image", "imagen"], ".jpg": ["file-image", "imagen"], ".jpeg": ["file-image", "imagen"],
            ".webp": ["file-image", "imagen"], ".ppt": ["file-ppt", "texto"], ".pptx": ["file-ppt", "texto"],
            ".txt": ["file-text", "texto"], ".zip": ["file-zip", "texto"]
        }[extension] || ["file", "texto"];
    }
    function enlaceDocumento(documento, accion, iconoAccion) {
        const enlace = elemento("a", "chat-archivo-boton");
        enlace.setAttribute("aria-label", accion + " " + documento.titulo);
        enlace.append(icono(iconoAccion), elemento("span", "", accion));
        return enlace;
    }
    function tarjetas(datos) {
        const docs = datos.documentos;
        const contenido = turno(docs.length === 0 ? "No encontré documentos con esos criterios. Puedes ajustar la búsqueda." :
            (datos.hay_mas ? "Estos son los primeros 20 resultados. Añade un criterio para acotar la búsqueda." :
                docs.length === 1 ? "Encontré un documento." : "Encontré " + docs.length + " documentos."), false, docs.length > 0);
        if (!docs.length) return;
        const lista = elemento("ul", "chat-resultados");
        for (const d of docs) {
            if (!/^[1-9]\d{0,18}$/.test(d.id) || typeof d.titulo !== "string") continue;
            const [dibujo, tipo] = tipoArchivo(d.extension);
            const item = elemento("li", "chat-archivo");
            const insignia = elemento("span", "chat-archivo-icono");
            insignia.dataset.tipo = tipo;
            insignia.append(icono(dibujo));
            const detalle = elemento("div", "chat-archivo-detalle");
            const formato = /^\.[a-z0-9]{1,12}$/i.test(d.extension) ? d.extension.slice(1).toUpperCase() : "Archivo";
            const metadatos = [formato, d.departamento].filter(Boolean).join(" · ");
            detalle.append(elemento("strong", "chat-archivo-titulo", d.titulo), elemento("span", "chat-archivo-metadatos", metadatos));
            const acciones = elemento("div", "chat-archivo-acciones");
            const enlace = enlaceDocumento(d, "Ver", "eye");
            enlace.href = "/documentos/" + d.id;
            enlace.target = "_blank";
            enlace.rel = "noopener";
            acciones.append(enlace);
            if (d.descargar === true) {
                const descarga = enlaceDocumento(d, "Descargar", "download-simple");
                descarga.href = "/documentos/" + d.id + "/descargar";
                acciones.append(descarga);
            }
            item.append(insignia, detalle, acciones);
            lista.append(item);
        }
        contenido.append(lista);
        mantenerPosicion();
    }
    function opcionesDuda(d) {
        if (d.tipo==="fecha_numerica" || d.tipo==="fechas_multiples") {
            return (d.opciones || []).map(f=>typeof f==="string"?{desde:f,hasta:f}:f);
        }
        if (d.tipo==="area") return d.opciones.filter(a=>opciones.rol==="admin"||a===opciones.areaUsuario).map(a=>({departamento:a}));
        if (d.tipo==="categoria") return d.opciones.map(c=>({categoria:c}));
        if (d.tipo==="obras") {
            const a=[{buscar:"obras"}];
            if (opciones.rol==="admin"||d.area===opciones.areaUsuario) a.push({departamento:d.area});
            return a;
        }
        return [];
    }
    const formatoFecha = new Intl.DateTimeFormat("es-MX", { dateStyle: "long", timeZone: "UTC" });
    function nombreOpcion(x) {
        if (x.desde) {
            const desde = formatoFecha.format(new Date(x.desde + "T00:00:00Z"));
            return x.desde === x.hasta ? desde : desde + " a " + formatoFecha.format(new Date(x.hasta + "T00:00:00Z"));
        }
        return x.departamento || x.categoria || "Obras como tema";
    }
    function completar(plan, respuesta) {
        const duda=plan.dudas[0];
        if (!duda) return null;
        const valor = respuesta.trim().toLowerCase();
        let elegida = opcionesDuda(duda).find(opcion =>
            nombreOpcion(opcion).toLowerCase() === valor ||
            (opcion.desde && (opcion.desde === opcion.hasta ? opcion.desde : opcion.desde + " a " + opcion.hasta) === valor)
        );
        if (!elegida && (duda.tipo==="mes_sin_anio" || duda.tipo==="rango_sin_anio") && /^(?:19|20)\d{2}$/.test(respuesta.trim())) {
            const year=Number(respuesta.trim());
            const inicio=duda.inicio || {mes:duda.mes,dia:1};
            const fin=duda.fin || {mes:duda.mes,dia:null};
            const local=(parte, final) => {
                const fecha=final && parte.dia===null
                    ? new Date(year,parte.mes+1,0) : new Date(year,parte.mes,parte.dia);
                if (fecha.getFullYear()!==year || fecha.getMonth()!==parte.mes) return null;
                return [year,String(parte.mes+1).padStart(2,"0"),String(fecha.getDate()).padStart(2,"0")].join("-");
            };
            const desde=local(inicio,false),hasta=local(fin,true);
            return desde && hasta && desde<=hasta
                ? {...plan,filtros:{...plan.filtros,desde,hasta},dudas:plan.dudas.slice(1),correccion:true} : null;
        }
        if (!elegida && /fecha|rango|anio/.test(duda.tipo)) {
            const texto=respuesta.replace(/^mejor\s+(?:del?\s+)?/i,"");
            const d=opts.detallar(texto,opts.categorias,opts.areas);
            if (d.filtros.desde && d.filtros.hasta && !d.filtros.buscar && !d.dudas.length) {
                elegida={desde:d.filtros.desde,hasta:d.filtros.hasta};
            }
        }
        return elegida?{...plan,filtros:{...plan.filtros,...elegida},dudas:plan.dudas.slice(1),correccion:true}:null;
    }
    function aclarar(plan) {
        pendientes=plan;
        const d=plan.dudas[0];
        const mensaje=d.tipo==="area"?"¿Qué departamento quieres consultar?":
            d.tipo==="categoria"?"¿Qué categoría quieres buscar?":d.tipo==="obras"?"¿Obras es el tema o el departamento?":
            ["mes_sin_anio","rango_sin_anio"].includes(d.tipo)?"¿De qué año es el periodo?":
            "¿Qué fecha o intervalo quieres usar?";
        const fila=turno(mensaje);
        for (const op of opcionesDuda(d)) {
            const b=elemento("button","boton-secundario",nombreOpcion(op)); b.type="button";
            b.addEventListener("click",()=>{
                if (pendientes!==plan || activo) return;
                void enviarTexto(nombreOpcion(op),{...plan,filtros:{...plan.filtros,...op},dudas:plan.dudas.slice(1),correccion:true});
            });
            fila.append(b);
        }
        mantenerPosicion();
    }
    async function interpretar(texto,trabajo) {
        if (dialogo.dataset.apoyo!=="1" || !token) return null;
        try {
            const r=await fetch("/asistente/interpretar?chat=true",{method:"POST",credentials:"same-origin",cache:"no-store",
                headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({texto}),signal:trabajo.signal});
            return r.status===200 && !r.redirected?await r.json():null;
        } catch { return null; }
    }
    async function consultar(ruta, trabajo, etapaResultados = false) {
        const r=await fetch(ruta,{credentials:"same-origin",cache:"no-store",signal:trabajo.signal});
        if (r.redirected || r.status===401) throw new Error("Tu sesión caducó. Vuelve a ingresar para continuar.");
        if (r.status===403) throw new Error("Tu cuenta no tiene acceso a ese departamento o recurso.");
        if (r.status===422) throw new Error("Revisa el folio, el departamento o las fechas que indicaste.");
        if (!r.ok) throw new Error("No pude completar la consulta. Inténtalo de nuevo.");
        if (etapaResultados) etapa(trabajo, "Preparando resultados");
        const datos=await r.json();
        if (datos.usuario_id!==opciones.usuarioId) throw new Error("La sesión cambió. Recarga la página para continuar.");
        return datos;
    }
    async function enviarTexto(texto,forzado) {
        if (!texto || activo) return;
        const trabajo=new AbortController(); activo=trabajo;
        enviar.disabled=true; formulario.setAttribute("aria-busy","true");
        turno(texto,true);
        etapa(trabajo,"Pensando");
        try {
            let plan=forzado || (pendientes && completar(pendientes,texto));
            if (!plan && pideRegistro && /^[1-9]\d{0,17}$/.test(texto)) {
                plan={tipo:"diagnostico",tema:"documento",registro:texto};
            }
            pideRegistro=false;
            if (!plan && pendientes && /^\d{1,4}(?:[./-]\d{1,4}){0,2}$/.test(texto)) {
                aclarar(pendientes); return;
            }
            const anterior=pendientes?.filtros || filtros;
            pendientes=null;
            if (!plan) {
                etapa(trabajo,"Interpretando solicitud");
                const apoyo=await interpretar(texto,trabajo);
                if (activo!==trabajo) return;
                plan=resolver(texto,anterior,opts,apoyo);
            }
            if (plan.tipo==="reiniciar") {
                filtros=null; turno("Listo. ¿Qué quieres buscar ahora?"); return;
            }
            if (plan.tipo==="mensaje") { turno(plan.texto); return; }
            if (plan.tipo==="ayuda") { turno(ayuda(plan.tema)); return; }
            if (plan.tipo==="diagnostico") {
                if (plan.tema==="documento" && !plan.registro) {
                    pideRegistro=true;
                    turno("¿Cuál es el número de registro interno del documento?");
                    return;
                }
                etapa(trabajo,"Interpretando solicitud");
                const q=new URLSearchParams({tema:plan.tema});
                if (plan.accion) q.set("accion",plan.accion);
                if (plan.registro) q.set("registro",plan.registro);
                const d=await consultar("/asistente/diagnostico?"+q,trabajo);
                if (activo===trabajo) turno(d.mensaje);
                return;
            }
            if (plan.correccion) etapa(trabajo,"Corrigiendo parámetros");
            if (plan.dudas.length) { aclarar({...plan,texto:plan.texto||texto}); return; }
            if (plan.expediente) {
                filtros=null;
                const fila=turno("Puedo abrir la búsqueda con ese folio de expediente.");
                const a=elemento("a","boton-secundario","Consultar expediente");
                a.href="/buscar?"+new URLSearchParams({q:plan.expediente}); fila.append(a); mantenerPosicion(); return;
            }
            const propuestos=Object.fromEntries(Object.entries(plan.filtros).filter(([,v])=>v));
            if (!Object.keys(propuestos).length) { turno("Escribe un título, folio o criterio de búsqueda."); return; }
            etapa(trabajo,"Buscando documentos");
            const d=await consultar("/asistente/documentos?"+new URLSearchParams(propuestos), trabajo, true);
            if (activo!==trabajo) return;
            filtros=propuestos;
            tarjetas(d);
        } catch (error) {
            if (activo===trabajo && !trabajo.signal.aborted) turno(error instanceof TypeError?"No pude conectar. Inténtalo de nuevo.":error.message);
        } finally { terminar(trabajo); }
    }
    function mostrarModelo(estado) {
        if (modelo.dataset.estado === estado) return;
        modelo.dataset.estado = estado;
        modelo.hidden = false;
        modelo.textContent = mensajesModelo[estado];
    }
    function detenerSondeoModelo() {
        clearTimeout(sondeoModelo);
        consultaModelo?.abort();
        consultaModelo = null;
    }
    async function actualizarModelo() {
        if (dialogo.dataset.apoyo !== "1") {
            mostrarModelo("reglas");
            return;
        }
        const consulta = new AbortController();
        consultaModelo = consulta;
        let estado = "sin_conexion";
        try {
            const r = await fetch("/asistente/estado-modelo", {cache:"no-store", signal:consulta.signal});
            if (r.ok && !r.redirected) {
                const datos = await r.json();
                if (Object.hasOwn(mensajesModelo, datos.estado)) estado = datos.estado;
            }
        } catch {
            // El chat conserva su alternativa local, aunque falle el sondeo.
        }
        if (consultaModelo !== consulta || !dialogo.open) return;
        consultaModelo = null;
        mostrarModelo(estado);
        const intervalo = estado === "cargando" ? 3000 : 15000;
        sondeoModelo = setTimeout(actualizarModelo, intervalo);
    }
    dialogo.addEventListener("close", () => { if (!dialogo.open) detenerSondeoModelo(); });
    window.addEventListener("pagehide", detenerSondeoModelo);
    abrir.addEventListener("click",()=>{
        if (!historial.childElementCount) reiniciar();
        dialogo.showModal();
        campo.focus();
        mantenerPosicion();
        detenerSondeoModelo();
        void actualizarModelo();
    });
    dialogo.querySelector("#abrir-busqueda-asistida")?.addEventListener("click",()=>dialogo.close(),{capture:true});
    historial.addEventListener("click", evento => {
        const sugerencia = evento.target.closest("[data-chat-sugerencia]");
        if (!sugerencia) return;
        campo.value = sugerencia.dataset.chatSugerencia;
        campo.focus();
    });
    window.addEventListener("pagehide",reiniciar);
    dialogo.querySelector("[data-chat-cerrar]").addEventListener("click",()=>dialogo.close());
    dialogo.querySelector("[data-chat-nuevo]").addEventListener("click",()=>{reiniciar(); campo.value=""; campo.focus();});
    formulario.addEventListener("submit",e=>{
        e.preventDefault(); if (activo || !campo.value.trim()) return;
        const texto=campo.value.trim(); campo.value=""; void enviarTexto(texto);
    });
    campo.addEventListener("keydown",e=>{
        if (e.key==="Enter" && !e.shiftKey && !e.isComposing) {e.preventDefault(); formulario.requestSubmit();}
    });
})();

