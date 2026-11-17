/* Planificación local, sin efectos sobre NexusGrid. */
((root) => {
    const norm = t => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    const limpio = t => norm(t).replace(/^[¿¡]+|[¿?¡!.]+$/g, "").trim();
    const ayuda = /^(?:como|donde|para que|que significa|que es|se puede|es posible|explicame)\b/;
    const escritura = /\b(?:borra(?:lo|me)?|elimina(?:lo)?|restaura|edita|modifica|actualiza|renombra|publica|sube|guarda|desactiva|activa|reemplaza|vincula|desvincula)\b/;
    const peticion = /^(?:[¿¡]\s*)?(?:(?:me\s+)?(?:puedes|podrías|podrias)\s+|(?:quiero|necesito)\s+(?:ver|consultar|encontrar|localizar)\s+|d[oó]nde\s+(?:est[aá]|qued[oó])\s+)?(?:ay[uú]dame\s+a\s+)?(?:b[uú]scame|busqa|encu[eé]ntrame|local[ií]zame|ub[ií]came|mu[eé]strame|muetstrame|ens[eé]ñame|s[aá]came|ch[eé]came|busca|buscar|encuentra|localiza|ubica|muestra|consulta|abre|ens[eé]ña)\b\s*/iu;
    function limpiarPeticion(t) {
        let frase = t.trim().replace(/^(?:(?:[¿¡]\s*)?(?:oye|ey|a\s*ver|aver|clippy|clipy|clpy|we|wey)[,:\s]+)+/iu, "");
        frase = frase.replace(/\s+(?:por\s*favor|porfa|pls|wey|we|porfas)[.!?]*$/iu, "").replace(/[?!.]+$/g,"");
        const sinInicio = frase.replace(/^(?:[¿¡]\s*)?me ayudas a\s+/iu,"").replace(peticion,"").replace(/^(?:quiero|necesito)\s+(?:ver|consultar|encontrar|localizar)\s+/iu,"");
        return sinInicio.trim() || frase.trim() || t;
    }
    function quitarMencion(buscar,mencion) {
        const tokens=t=>norm(t).replace(/[^\p{L}\p{N}\s-]/gu," ").split(/\s+/).filter(Boolean);
        const a=tokens(buscar), b=tokens(mencion);
        const i=b.length?a.findIndex((_,j)=>b.every((t,k)=>a[j+k]===t)):-1;
        return i<0?buscar:[...a.slice(0,i),...a.slice(i+b.length)].join(" ");
    }
    function fechaLocal(dias) {
        const d = new Date(); d.setDate(d.getDate() + dias);
        return [d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-");
    }
    function criterios(entrada, opts, apoyo) {
        const texto = limpiarPeticion(entrada);
        const base = opts.detallar(texto, opts.categorias, opts.areas);
        const f = {...base.filtros};
        const t = limpio(texto);
        const id = t.match(/\b(?:registro(?:\s+interno)?|ficha|documento\s+numero|archivo\s+numero)\s*(?::|#)?\s+([1-9]\d{0,17})(?![\w/-])/);
        const folio = t.match(/\bfolio\s*(?::|#)?\s+((?:[a-z]{1,12}-)?\d[a-z0-9/-]{0,58})\b/);
        const ref = apoyo?.enlaces?.find(x => ["registro","folio","titulo"].includes(x.tipo));
        if (id || ref?.tipo === "registro") {
            f.registro=id?.[1] || ref.valor; delete f.buscar;
        } else if (!base.expediente && (folio || ref?.tipo === "folio")) {
            f.folio=folio?.[1] || ref.valor; delete f.buscar;
        } else if (ref?.tipo === "titulo") f.buscar=ref.valor;
        const extra = {...apoyo?.criterios};
        const antier=t.match(/\b(?:antier|anteayer)\b/);
        const dudasFecha=base.dudas.some(d=>/fecha|rango|anio/.test(d.tipo));
        if ((apoyo?.dias_relativos === -2 || antier) && !f.desde && !f.hasta && !dudasFecha &&
                !/\b(?:hoy|ayer|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b/.test(t)) {
            extra.desde=extra.hasta=fechaLocal(-2);
        }
        for (const k of ["departamento","oficio","desde","hasta"]) {
            if (!extra[k] || f[k] || (["desde","hasta"].includes(k) && dudasFecha)) continue;
            f[k]=extra[k];
            const m=apoyo?.consumir?.[k] || (k==="desde" && antier?.[0]);
            if (f.buscar && m) f.buscar=quitarMencion(f.buscar,m);
        }
        return {filtros:f,dudas:base.dudas,expediente:base.expediente};
    }
    function resolver(texto, previo, opts, apoyo) {
        const t = limpio(texto);
        const mensaje=texto=>({tipo:"mensaje",texto});
        if (/^(?:(?:empieza|comienza|empezar|comenzar) de nuevo|nueva (?:busqueda|conversacion))$/.test(t)) return {tipo:"reiniciar"};
        const nueva=t.match(/^(?:nueva busqueda|busqueda nueva|empecemos de nuevo)\s*[:;,]?\s+(.+)/);
        if (nueva) return resolver(nueva[1],null,opts,apoyo);
        if (/^(hola|buenos dias|buenas tardes|buenas noches|gracias|que onda)$/.test(t)) return mensaje("Puedo buscar documentos por tema, departamento, fecha o folio.");
        const cambia = /^cambia (?:el |la )?(?:departamento|area|fecha|folio|oficio|criterio)\s+(?:a|por)\s+/.test(t) &&
            !/\b(?:del documento|del archivo|del oficio|al documento)\b/.test(t);
        const quitar = /^(?:quita|quitar|conserva|olvida los filtros)\b/.test(t);
        const correccion = cambia || quitar || /^(?:mejor|ahora solo|solo de)\b/.test(t) ||
            (previo && (opts.areas.some(a=>norm(a)===t.replace(/^(?:de|del|en)\s+/,"")) ||
            /^(?:de |del )?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)(?: de \d{4})?$/.test(t)));
        const negacion=apoyo?.avisos?.includes("negacion") || /\b(?:no+|sin|nel|nunca)\b/.test(t);
        const negada=negacion && !/\bno solo\b/.test(t) && (/\bno\s+(?:me\s+)?(?:abras|muestres|busques|descargues|ensenes|listes|consultes|traigas)\b/.test(t) || escritura.test(t) || /\b(?:mejor|excepto|excluye|pero|no de|no del|no el|no la|sin incluir|sin los|sin las|sin el|sin la)\b/.test(t));
        if (negada || (!ayuda.test(t) && !quitar && !cambia && (escritura.test(t) || apoyo?.avisos?.includes("solo_lectura")))) {
            return mensaje("Puedo buscar y consultar documentos. Indica qué quieres encontrar y qué criterio sí debo usar.");
        }
        if (apoyo?.avisos?.includes("area_no_disponible")) return mensaje("Tu cuenta no puede consultar ese departamento.");
        if (apoyo?.avisos?.some(k=>["folios_varios","referencias_varias"].includes(k))) return mensaje("Mencionaste varias referencias. Indica una para buscar.");
        if (correccion) {
            if (!previo) return mensaje("Primero dime qué documento quieres buscar.");
            let instruccion=t.replace(/^cambia (?:el |la )?(?:departamento|area|fecha|folio|oficio|criterio) (?:a|por) /,"mejor ")
                .replace(/^(?:ahora solo|solo) /,"mejor ");
            if (cambia && /\b(?:folio|oficio)\b/.test(t.split(/\s+(?:a|por)\s+/)[0]) && !/^mejor (?:oficio|folio)\b/.test(instruccion)) {
                instruccion=instruccion.replace(/^mejor /,/\boficio\b/.test(t.split(/\s+(?:a|por)\s+/)[0])?"mejor oficio ":"mejor folio ");
            }
            if (!/^(?:mejor|quita|conserva|olvida)\b/.test(instruccion)) instruccion="mejor "+instruccion;
            const anterior = {...previo};
            if (/^quita(?:r)? (?:el )?(?:folio|registro)$/.test(instruccion)) {
                if (instruccion.endsWith("folio")) { delete anterior.folio; delete anterior.oficio; }
                else delete anterior.registro;
                return Object.values(anterior).some(Boolean)?{tipo:"buscar",filtros:anterior,dudas:[],correccion:true}:{tipo:"reiniciar"};
            }
            const p=opts.contextual(instruccion,{estado:{filtros:previo},categorias:opts.categorias,areas:opts.areas},opts.detallar);
            if (p.tipo==="limpiar_filtros") return {tipo:"reiniciar"};
            const propuesto=criterios(instruccion.replace(/^mejor\s+(?:busca\s+)?/,""),opts,apoyo);
            const cambio=["folio","registro"].some(k=>k in propuesto.filtros)||p.tipo!=="cambios"?propuesto.filtros:p.cambios;
            const dudas=p.tipo==="cambios"?[]:propuesto.dudas;
            const campos=Object.keys(cambio).filter(k=>k!=="buscar");
            if (new Set(campos.map(k=>["desde","hasta"].includes(k)?"fecha":k)).size>1 || propuesto.expediente ||
                    (!/^mejor\b/.test(instruccion) && p.tipo!=="cambios")) return mensaje("Indica un criterio a la vez o escribe una búsqueda nueva.");
            if (dudas.length && dudas.some(d=>/fecha|rango|anio/.test(d.tipo))) {delete anterior.desde; delete anterior.hasta;}
            if (campos.some(k=>["folio","registro","oficio"].includes(k))) {
                delete anterior.folio; delete anterior.registro; delete anterior.oficio;
            }
            if (campos.length||dudas.length) delete cambio.buscar;
            if (!Object.keys(cambio).length && !dudas.length && p.tipo!=="cambios") return mensaje("Indica el valor que quieres usar.");
            return {tipo:"buscar",filtros:{...anterior,...cambio},dudas,correccion:true};
        }
        const tema=opts.clasificar(texto,{estado:{filtros:previo||{}},categorias:opts.categorias,areas:opts.areas});
        if (tema.tipo==="diagnostico") return tema;
        const busquedaSemantica=apoyo?.intencion==="busqueda_documental" && !ayuda.test(t);
        if (tema.tipo==="ayuda" && !peticion.test(t) && !busquedaSemantica) return tema;
        if (ayuda.test(t) && !peticion.test(t)) {
            return {tipo:"ayuda",tema:opts.ayudaValida(apoyo?.intencion)?apoyo.intencion:"busqueda"};
        }
        const plan=criterios(texto,opts,apoyo);
        if (!plan.dudas.length && apoyo?.avisos?.includes("fecha_ambigua")) {
            delete plan.filtros.desde; delete plan.filtros.hasta;
            plan.dudas.push({tipo:"fecha_manual"});
        }
        return {...plan,tipo:"buscar",correccion:false};
    }
    root.sigedPlanClippy={resolver,fechaLocal,limpiarPeticion};
})(globalThis);

