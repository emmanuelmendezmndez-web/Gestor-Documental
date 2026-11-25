/* Planificación local, sin efectos sobre NexusGrid. */
((root) => {
    const norm = t => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    const limpio = t => norm(t).replace(/^[¿¡]+|[¿?¡!.]+$/g, "").trim();
    const procedimiento = /^(?:como|por que|para que|que (?:hago|significa|es|puedo|debo)|se puede|es posible|explicame|me explicas|(?:me puedes|puedes) explicar|dime como|ayuda)\b/;
    const escritura = /\b(?:borra(?:lo|me)?|elimina(?:lo)?|restaura|edita|modifica|actualiza|renombra|publica|sube|guarda|desactiva|activa|reemplaza|vincula|desvincula)\b/;
    const peticion = /^(?:[¿¡]\s*)?(?:(?:me\s+)?(?:puedes|podr[ií]as|podr[aá]s|puede|ayudas\s+a)\s+)?(?:ay[uú]dame\s+a\s+)?(?:me\s+)?(?:b[uú]scame|busqa|encu[eé]ntrame|local[ií]zame|ub[ií]came|mu[eé]strame|muetstrame|ens[eé]ñame|tr[aá]eme|s[aá]came|ch[eé]came|busca(?:s|r(?:me)?)?|encuentras?|encontrar(?:me)?|localiza(?:s|r(?:me)?)?|ubica(?:s|r(?:me)?)?|muestras?|mostrar(?:me)?|consulta[rs]?|abres?|abrir|ens[eé]ña(?:s|r(?:me)?)?|trae(?:s|r(?:me)?)?|dame|das)\b\s*/iu;
    const ubicacion = /^(?:[¿¡]\s*)?(?:en\s+)?d[oó]nde\s+(?:qued[oó]|est[aá](?:n)?|encuentro|localizo)\s+/iu;
    const deseo = /^(?:[¿¡]\s*)?(?:quiero|necesito)\s+(?:ver|consultar|encontrar|localizar)\s+/iu;
    const unidades = "documentos?|archivos?|ficheros?|oficios?|informes?|contratos?|actas?|certificados?|inventarios?|bit[aá]coras?";
    const cantidades = ["cero","uno","dos","tres","cuatro","cinco","seis","siete","ocho","nueve","diez","once","doce","trece","catorce","quince","dieciséis","diecisiete","dieciocho","diecinueve","veinte"];
    const numero = "(?:\\d+|" + cantidades.join("|") + "|dieciseis)";
    const ordinal = "(?:[uú]ltim[oa]s?|primer(?:[oa]s?)?)";
    const prefijoOrden = new RegExp("^(?:(?:el|la|los|las)\\s+)?(?:("+numero+")\\s+)?("+ordinal+")\\s+(?:("+numero+")\\s+)?("+unidades+")\\b","iu");
    const cantidadAnterior = new RegExp("^(?:(?:los|las)\\s+)?("+numero+")\\s+("+unidades+")\\s*$","iu");
    const preguntaOrden = new RegExp("^(?:[¿]?cu[aá]l(?:es)?\\s+(?:fue(?:ron)?|es|son)\\s+)(?=(?:el|la|los|las)\\s+"+ordinal+"\\s+)","iu");
    const deseoDocumento = new RegExp("^(?:necesito|quiero)\\s+(?=(?:el|la|un|una|los|las)\\s+(?:"+unidades+")\\s+que\\s+(?:habla|trata)\\s+(?:sobre|de)\\s+)","iu");
    const temaDocumental = /\b(?:documentos?|archivos?|ficheros?|oficios?|informes?|contratos?|actas?|certificados?|inventarios?|bitacoras?|folios?|registros?|expedientes?|pdfs?)\b/;
    const negacionAccion = /\b(?:no+|nunca|jamas|ni)\s+(?:(?:me|lo|la|los|las|quiero que|vayas a)\s+)*(?:busqu\w*|busca\w*|descarg\w*|muestr\w*|mostr\w*|ens[eé]n\w*|abr\w*|consult\w*|list\w*|traig\w*|locali[cz]\w*|inclu\w*|borra\w*|elimin\w*|edit\w*)\b/;
    const exclusion = /\b(?:excepto|salvo|menos los|menos las|exclu(?:ir|ye|yan|yas)|sin (?:incluir|contar|mostrar|los|las|el|la)|no (?:de|del|el|la))\b/;
    const categoriasSingulares = {Contratos:"contrato",Actas:"acta",Certificados:"certificado",Informes:"informe",Bitacoras:"bitacora",Inventarios:"inventario"};
    const nombreArchivo = /^([^«»“”"/?!,:;]+?\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|jpe?g|png|webp|zip))(?=$|[\s,;?])/iu;
    const folioMarcado = /\b(?:(?:con\s+)?(?:el\s+)?folio)\s*(?:[:#]\s*)?[«“"]?((?:[a-z]{1,12}[-/])?\d[a-z0-9/-]{0,58})\b[»”"]?/iu;
    const folioSuelto = /\b(?!exp[-/]|of[-/])[a-z]{2,12}[-/]\d{1,10}[-/][a-z0-9/-]*\d[a-z0-9/-]*\b/iu;
    const oficioLiteral = /\b(?:oficio|of\.)\s*(?:n[uú]mero|num\.?|no\.?)?\s*[:#]?\s*(?=[a-z0-9/-]*\d)[a-z0-9]+(?:[-/][a-z0-9]+)*\b|\bof-\d+(?:[-/]\w+)*\b/iu;
    const registroMarcado = /\b(?:registro(?:\s+interno)?|ficha|documento\s+n[uú]mero|archivo\s+n[uú]mero)\s*(?:[:#]\s*)?([1-9]\d{0,17})(?![\w/-])/iu;

    function sinCortesia(t) {
        return t.trim().replace(/^(?:[¿¡]*\s*(?:oye|ey|a\s*ver|aver|clippy|clipy|clpy|we|wey|por\s*favor|porfa|porfas|pls)[,:\s]+)+/iu, "")
            .replace(/[,;\s]+(?:por\s*favor|porfa|pls|wey|we|porfas)[.!?]*$/iu, "").trim();
    }
    function sinInicioTemporal(t) {
        const resto = t.replace(/^(?:[¿¡]\s*)?ahora\s+/iu, "");
        return peticion.test(resto) || deseo.test(resto) ? resto : t;
    }
    function limpiarPeticion(t) {
        const frase = sinInicioTemporal(sinCortesia(t)).replace(/^[¿¡\s]+|[?!.]+$/g, "");
        return sinCortesia(frase.replace(peticion,"").replace(/^lista(?:me)?\s+/iu,"").replace(preguntaOrden,"").replace(deseoDocumento,"").replace(deseo,"").replace(
            ubicacion, inicio => temaDocumental.test(norm(frase.slice(inicio.length))) ? "" : inicio
        )).trim();
    }
    function quitarParte(texto, coincidencia) {
        return texto.slice(0, coincidencia.index) + " " + texto.slice(coincidencia.index + coincidencia[0].length);
    }
    function referenciaTitulo(texto, apoyo) {
        const folio = texto.match(folioMarcado);
        const citas = [...texto.matchAll(/«([^»]+)»|“([^”]+)”|"([^"]+)"|'([^']+)'/gu)]
            .filter(cita => !folio || cita.index < folio.index ||
                cita.index >= folio.index + folio[0].length);
        if (citas.length > 1) return {varios:true};
        const cita = citas[0];
        if (cita) return {valor:cita[1]||cita[2]||cita[3]||cita[4],literal:cita[0],resto:quitarParte(texto,cita)};
        const nombrado = texto.match(/\b(?:que se llama|con el t[ií]tulo|titulado|titulada|llamado|llamada)\s+(.+)$/iu);
        if (nombrado) {
            const fin = nombrado[1].search(/\b(?:y|luego|despu[eé]s)\s+(?:borra|elimina|edita|modifica|actualiza|renombra|descarga|publica|sube|guarda|activa|desactiva|reemplaza|vincula|desvincula)\b/iu);
            if (fin !== -1) return {varios:true};
            return {valor:nombrado[1],literal:nombrado[1],resto:texto.slice(0,nombrado.index)};
        }
        const marcador = texto.match(/\b(?:el |la |un |una )?(?:archivo|documento|fichero)\s+(?:con\s+nombre\s+)?(?=\S)/iu);
        const inicio = marcador ? marcador.index+marcador[0].length : 0;
        const archivo = texto.slice(inicio).match(nombreArchivo);
        if (archivo) return {valor:archivo[1],literal:archivo[1],resto:texto.slice(0,marcador?.index ?? 0)+" "+texto.slice(inicio+archivo[0].length)};
        if (apoyo?.tipo === "titulo") {
            // Mantiene los índices del texto original al quitar tildes combinadas.
            const valor = apoyo.valor.normalize("NFC");
            const fuente = texto.normalize("NFC");
            const posicion = fuente.toLocaleLowerCase("es").indexOf(valor.toLocaleLowerCase("es"));
            if (posicion >= 0) return {valor:apoyo.valor,literal:fuente.slice(posicion,posicion+valor.length),
                resto:fuente.slice(0,posicion)+" "+fuente.slice(posicion+valor.length)};
        }
        return null;
    }
    function quitarMencion(buscar,mencion) {
        const tokens=t=>norm(t).replace(/[^\p{L}\p{N}\s-]/gu," ").split(/\s+/).filter(Boolean);
        const a=tokens(buscar), b=tokens(mencion);
        const i=b.length?a.findIndex((_,j)=>b.every((t,k)=>a[j+k]===t)):-1;
        return i<0?buscar:[...a.slice(0,i),...a.slice(i+b.length)].join(" ");
    }
    function orientacion(texto, referenciaConcreta) {
        const t = limpio(texto);
        // Examina el objeto de la petición, además de su verbo inicial.
        const objeto = limpio(limpiarPeticion(texto));
        const explicacion = /\b(?:explicame|me explicas|me puedes explicar|dime como|solo dime como|primero explicame)\b/.test(t);
        const interfaz = /^(?:(?:el|la|los|las|un|una) )?(?:boton|opcion|menu|pantalla|apartado|seccion|configuracion)\b/.test(objeto);
        const informativa = procedimiento.test(t) || procedimiento.test(objeto) || explicacion ||
            (!referenciaConcreta && interfaz);
        return {informativa, texto:procedimiento.test(objeto) ? objeto : "como " + texto};
    }
    function fechaLocal(dias) {
        const d = new Date(); d.setDate(d.getDate() + dias);
        return [d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-");
    }
    function criterios(entrada, opts, apoyo) {
        const texto = limpiarPeticion(entrada.normalize("NFC"));
        const ref = apoyo?.enlaces?.find(x => ["registro","folio","titulo"].includes(x.tipo) &&
            norm(texto).includes(norm(x.valor)));
        const titulo = referenciaTitulo(texto, ref);
        const resto = titulo ? titulo.resto : texto;
        const id = resto.match(registroMarcado);
        const folio = resto.match(folioMarcado) || resto.match(folioSuelto);
        let restante = folio ? quitarParte(resto, folio) : id ? quitarParte(resto,id) : resto;
        const inicial = restante.trim().match(prefijoOrden);
        const orden = restante.match(/\bm[aá]s\s+(recientes?|antigu[oa]s?|viej[oa]s?)\b/iu);
        let direccion, limite;
        if (inicial || orden) {
            const descriptor = inicial ? inicial[2] : orden[1];
            direccion = /^(?:ultimo|ultima|reciente)/.test(norm(descriptor)) ? "registro_desc" : "registro_asc";
            const anterior = !inicial && restante.slice(0,orden.index).trim().match(cantidadAnterior);
            const cantidad = inicial ? inicial[1] || inicial[3] : anterior?.[1];
            limite = cantidad ? (/^\d+$/.test(cantidad) ? Number(cantidad) : cantidades.findIndex(n=>norm(n)===norm(cantidad))) : (/s$/i.test(descriptor) ? 20 : 1);
            if (limite < 1 || limite > 20) return {tipo:"mensaje",texto:"Puedo mostrar entre 1 y 20 documentos. Indica una cantidad en ese intervalo."};
            if (inicial) restante = inicial[4] + restante.trim().slice(inicial[0].length);
            else restante = (anterior ? anterior[2] : restante.slice(0,orden.index)) + " " + restante.slice(orden.index+orden[0].length);
            // Consume la descripción del alta solo cuando sigue al sustantivo documental.
            restante = restante.replace(new RegExp("(^|\\s)("+unidades+")\\s+(?:(?:que\\s+se\\s+(?:(?:haya|hayan|ha|han)\\s+)?)?(?:subid[oa]s?|registrad[oa]s?|subi[oó]|subieron|registr[oó]|registraron))(?:\\s+(?:al|en\\s+el)\\s+gestor)?(?![\\p{L}\\p{N}_])","iu"),"$1$2");
        }
        restante = restante.replace(new RegExp("^((?:(?:el|un|los)\\s+)?(?:"+unidades+"))\\s+que\\s+(?:habla|trata)\\s+(?:sobre|de)\\s+","iu"),"$1 ");
        const marcaCategoria = restante.match(/\bcategor[ií]a\s*(?::\s*)?/iu);
        const inicioCategoria = marcaCategoria ? marcaCategoria.index + marcaCategoria[0].length : 0;
        const nombreCategoria = norm(restante.slice(inicioCategoria));
        const categoria = marcaCategoria && opts.categorias.find(c =>
            nombreCategoria === norm(c) || nombreCategoria.startsWith(norm(c)+" ")
        );
        if (categoria) restante = restante.slice(0,marcaCategoria.index) + " " + restante.slice(inicioCategoria+categoria.length);
        const base = opts.detallar(restante, opts.categorias, opts.areas);
        const f = {...base.filtros};
        if (direccion) {
            f.orden = direccion;
            f.limite = String(limite);
        }
        if (categoria) f.categoria = categoria;
        const t = limpio(resto);
        if (titulo) {
            f.buscar = titulo.valor.trim().slice(0,200);
            if (!/\bcategoria\b/.test(t)) delete f.categoria;
            if (id) f.registro=id[1];
            if (folio && !base.expediente) f.folio=folio[1] || folio[0];
        } else if (id || ref?.tipo === "registro") {
            f.registro=id?.[1] || ref.valor; delete f.buscar;
        } else if (!base.expediente && (folio || ref?.tipo === "folio")) {
            const valor=folio ? (folio[1] || folio[0]) : ref.valor;
            if (/^exp[-/]\d{4}[-/]\d+$/i.test(valor)) return {filtros:f,dudas:base.dudas,expediente:valor};
            f.folio=valor; delete f.buscar;
        } else {
            const singular = categoriasSingulares[f.categoria];
            if (!direccion && singular && f.buscar && !/\bcategoria\b/.test(t) &&
                    new RegExp("\\b"+singular+"\\b").test(t) && !new RegExp("\\b"+singular+"(?:s|es)\\b").test(t)) {
                f.buscar = (singular+" "+f.buscar).slice(0,200);
                delete f.categoria;
            }
        }
        const extra = {...apoyo?.criterios};
        // Una mención dentro de un título o folio pertenece al dato literal.
        // Las menciones externas de spaCy siguen disponibles como filtros.
        if (titulo || folio) {
            for (const k of Object.keys(extra)) {
                const mencion = apoyo?.consumir?.[k === "hasta" ? "desde" : k];
                if (!mencion || !norm(restante).includes(norm(mencion))) delete extra[k];
            }
        }
        const antier=t.match(/\b(?:antier|anteayer)\b/);
        const dudasFecha=base.dudas.some(d=>/fecha|rango|anio/.test(d.tipo));
        if (((!titulo && !folio && apoyo?.dias_relativos === -2) || antier) && !f.desde && !f.hasta && !dudasFecha &&
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
        const frase = sinCortesia(texto.normalize("NFC"));
        const t = limpio(frase);
        const mensaje=texto=>({tipo:"mensaje",texto});
        if (/^(?:(?:empieza|comienza|empezar|comenzar) de nuevo|nueva (?:busqueda|conversacion))$/.test(t)) return {tipo:"reiniciar"};
        const nueva=t.match(/^(?:nueva busqueda|busqueda nueva|empecemos de nuevo)\s*[:;,]?\s+(.+)/);
        if (nueva) return resolver(nueva[1],null,opts,apoyo);
        if (/^(hola|buenos dias|buenas tardes|buenas noches|gracias|que onda)$/.test(t)) return mensaje("Puedo buscar documentos por tema, departamento, fecha o folio.");
        const inicio = sinInicioTemporal(frase);
        const peticionInicial = limpio(inicio.match(peticion)?.[0] || "");
        const sinPeticion = limpiarPeticion(frase);
        const tituloLiteral = referenciaTitulo(sinPeticion);
        const folio = sinPeticion.match(folioMarcado) || sinPeticion.match(folioSuelto) || sinPeticion.match(oficioLiteral);
        const registro = sinPeticion.match(registroMarcado);
        const expediente = sinPeticion.match(/\bexp[-/]\d{4}[-/]\d+\b/i);
        const referenciaConcreta = Boolean(tituloLiteral || folio || registro || expediente);
        const criterioDocumental = referenciaConcreta || temaDocumental.test(t);
        const pideDocumento = (criterioDocumental && (peticionInicial || deseo.test(inicio) || ubicacion.test(t) || preguntaOrden.test(inicio) || deseoDocumento.test(inicio) || /^lista(?:me)?\s/iu.test(inicio))) ||
            /\b(?:busc(?:a|ar|ame|as|arme)|busqa|encuentr\w*|encontrar(?:me)?|localiz\w*|ubic\w*)$/.test(peticionInicial);
        if (tituloLiteral?.varios && (pideDocumento || /^[«“"']/.test(t)) && !procedimiento.test(t)) {
            return mensaje("Indica un solo título y delimítalo con comillas si la frase incluye otras instrucciones.");
        }
        const literal = tituloLiteral?.literal || folio?.[0];
        const protegeLiteral = literal && !procedimiento.test(t);
        let exterior = protegeLiteral ? frase.replace(literal, " ") : frase;
        if (protegeLiteral && tituloLiteral && folio && !tituloLiteral.literal.includes(folio[0])) {
            exterior = exterior.replace(folio[0], " ");
        }
        const instruccion = limpio(exterior);
        const orientacionPedida = orientacion(exterior, referenciaConcreta);
        const tema=opts.clasificar(exterior,{estado:{filtros:previo||{}},categorias:opts.categorias,areas:opts.areas});
        if (tema.tipo==="ayuda" && (["cerrar_sesion","iniciar_sesion","sesion","contrasena_olvidada","conteo_documentos","conteo_no_disponible"].includes(tema.tema) ||
                (procedimiento.test(t) && !pideDocumento))) return tema;
        const soloAyuda = instruccion.match(/^(?:solo|solamente|nada mas)\s+(.+)$/);
        const partes = instruccion.match(/^(.*?)(?:[,;.]|\bpero\b)\s*(?:(?:solo|solamente|nada mas)\s+)?(.+)$/);
        const pregunta = soloAyuda?.[1] || (partes && negacionAccion.test(partes[1]) ? partes[2] : "");
        if (/^(?:dime|explicame|me explicas|me puedes explicar)\s+como\b/.test(pregunta)) {
            const vista = /\bcomo\s+(?:puedo\s+)?(?:ver|abrir)(?:lo|la|los|las)\b/.test(pregunta);
            const orientacion = opts.clasificar(vista ? pregunta + " el documento" : pregunta);
            if (orientacion.tipo === "ayuda") return orientacion;
        }
        const cambioExplicito = frase.match(/^[¿¡\s]*cambia (?:el |la )?(departamento|[aá]rea|fecha|folio|oficio|criterio)\s+(?:a|al|por)\s+(.+?)\s*[?!.]*$/iu);
        const cambia = cambioExplicito &&
            !/\b(?:del documento|del archivo|del oficio|al documento)\b/.test(t);
        const quitar = /^(?:quita|quitar|conserva|olvida los filtros)\b/.test(t);
        const correccion = cambia || quitar || /^(?:mejor|ahora solo|solo de)\b/.test(t) ||
            (previo && (opts.areas.some(a=>norm(a)===t.replace(/^(?:de|del|en)\s+/,"")) ||
            /^(?:de |del )?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)(?: de \d{4})?$/.test(t)));
        if (exclusion.test(instruccion)) return mensaje("Todavía no puedo excluir criterios de una búsqueda. Indica qué criterio sí debo usar.");
        const negada = negacionAccion.test(instruccion) ||
            (/\b(?:no+|sin|nel|nunca|jamas)\b/.test(instruccion) && /\b(?:mejor|pero)\b/.test(instruccion));
        const descarga = /(?:^|\b(?:y|luego|despues)\s+)(?:(?:me puedes|puedes|podrias)\s+)?(?:descarga(?:me|lo|la|los|las)?|descargar)\b/.test(instruccion);
        if (negada || (!protegeLiteral && apoyo?.avisos?.includes("negacion")) || descarga || (!orientacionPedida.informativa && !quitar && !cambia &&
                (escritura.test(instruccion) || (!protegeLiteral && apoyo?.avisos?.includes("solo_lectura"))))) {
            return mensaje("Puedo buscar y consultar documentos. Indica qué quieres encontrar y qué criterio sí debo usar.");
        }
        if (!protegeLiteral && apoyo?.avisos?.includes("area_no_disponible")) return mensaje("Tu cuenta no puede consultar ese departamento.");
        if (apoyo?.avisos?.some(k=>["folios_varios","referencias_varias"].includes(k)) && !tituloLiteral) {
            return mensaje("Mencionaste varias referencias. Indica una para buscar.");
        }
        const referencias = [...sinPeticion.matchAll(new RegExp(folioMarcado.source,"giu"))];
        if (!tituloLiteral && referencias.length > 1) return mensaje("Mencionaste varios folios. Indica uno para buscar.");
        if (orientacionPedida.informativa && !protegeLiteral && tema.tipo !== "diagnostico") {
            const ayuda = opts.clasificar(orientacionPedida.texto);
            if (ayuda.tipo === "ayuda") return ayuda;
        }
        if (correccion) {
            if (!previo) return mensaje("Primero dime qué documento quieres buscar.");
            const campo = cambia && norm(cambioExplicito[1]);
            let instruccion=cambia ? "mejor "+cambioExplicito[2] : t.replace(/^(?:ahora solo|solo) /,"mejor ");
            if (["departamento","area"].includes(campo)) instruccion="mejor departamento "+cambioExplicito[2];
            if (["folio","oficio"].includes(campo) && !/^mejor (?:oficio|folio)\b/i.test(instruccion)) {
                instruccion=instruccion.replace(/^mejor /, "mejor "+campo+" ");
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
        if (tema.tipo==="diagnostico") return tema;
        const fraseDocumental = /^(?:(?:el|la|los|las|un|una) )?(\S+)/.exec(t)?.[1];
        const temaDirecto = Boolean(fraseDocumental && temaDocumental.test(fraseDocumental));
        const referenciaDirecta = referenciaConcreta && (temaDirecto || /^[«“"']/.test(t) ||
            [tituloLiteral?.literal, folio?.[0], registro?.[0], expediente?.[0]]
                .some(valor => valor && norm(sinPeticion).startsWith(norm(valor))));
        const sugerida = apoyo?.analisis && apoyo.analisis.estado !== "aceptada" ? null :
            apoyo?.intencion === "sesion" ? "sesion_general" : apoyo?.intencion;
        const referenciaExtraida = apoyo?.criterios?.oficio || apoyo?.enlaces?.some(e =>
            ["folio", "registro", "titulo"].includes(e.tipo) &&
            norm(frase).includes(norm(e.valor)));
        // La intención temática orienta la ayuda. Para buscar se exige evidencia documental
        // en el texto o una referencia concreta, incluso si el modelo propone buscar.
        const consultaIndirecta = referenciaConcreta &&
            /^(?:lo de|el de|la de|sobre|respecto a)\b/.test(t);
        if (orientacionPedida.informativa && !pideDocumento && opts.ayudaValida(sugerida)) {
            return {tipo:"ayuda",tema:sugerida};
        }
        if ((orientacionPedida.informativa && !protegeLiteral) ||
                (!pideDocumento && !(referenciaDirecta || temaDirecto || consultaIndirecta))) {
            if (tema.tipo==="ayuda") return tema;
            if (tema.motivo==="varios_temas") return mensaje("¿Sobre qué función de NexusGrid necesitas ayuda?");
            if (!criterioDocumental && opts.ayudaValida(sugerida)) return {tipo:"ayuda",tema:sugerida};
            const parcial = criterios(frase, opts, apoyo);
            if (parcial.tipo === "mensaje") return parcial;
            const extraidos = Object.values(apoyo?.criterios || {}).some(Boolean) || referenciaExtraida;
            if (!orientacionPedida.informativa && (extraidos || folio || registro || expediente) &&
                    Object.values(parcial.filtros).some(Boolean)) {
                // Conserva la extracción, pero pide el propósito pendiente antes de consultar.
                delete parcial.filtros.buscar;
                if (Object.values(parcial.filtros).some(Boolean)) {
                    return {...parcial, tipo:"buscar", correccion:false,
                        dudas:[...parcial.dudas, {tipo:"proposito"}], consultar_modelo:!apoyo};
                }
            }
            return {...mensaje("¿Buscas un documento o necesitas ayuda con una función de NexusGrid? Indica el título, folio o apartado."),
                consultar_modelo:!apoyo};
        }
        const plan=criterios(frase,opts,apoyo);
        if (plan.tipo === "mensaje") return plan;
        if (!tituloLiteral && pideDocumento && /\b(?:en (?:su|el) nombre|en el nombre del archivo)$/.test(t) &&
                /\bpalabra\b/.test(t)) {
            const palabra = sinPeticion.match(/\bpalabra\s+(.+?)\s+en\s+(?:su nombre|el nombre(?: del archivo)?)$/iu);
            if (palabra) return mensaje("La búsqueda revisa título, nombre de archivo y descripción. Para buscar en los tres, escribe «Busca "+palabra[1]+"».");
        }
        if (!tituloLiteral && plan.filtros.orden && /^(?:(?:el|un|los|unos)\s+)?pdfs?\s+m[aá]s\s+/iu.test(sinPeticion)) {
            return mensaje("La búsqueda del chat no filtra por extensión PDF. Puedes pedir los documentos más recientes o antiguos de todos los formatos.");
        }
        if (!tituloLiteral && !plan.dudas.length && apoyo?.avisos?.includes("fecha_ambigua")) {
            delete plan.filtros.desde; delete plan.filtros.hasta;
            plan.dudas.push({tipo:"fecha_manual"});
        }
        if (!Object.values(plan.filtros).some(Boolean) && !plan.dudas.length && !plan.expediente) {
            return mensaje("Escribe un título, folio o criterio de búsqueda.");
        }
        return {...plan,tipo:"buscar",correccion:false};
    }

    // Solo las marcas contiguas al sustantivo documental tienen valor de orden o cantidad.
    const formatos = "pdfs?|docx|xlsx|pptx";
    const cantidadLista = numero+"(?:\\s+(?:o|u)\\s+"+numero+")?";
    const cabeceraLista = new RegExp("^(?:(?:el|la|los|las)\\s+)?(?:("+ordinal+")\\s+)?(?:("+cantidadLista+")\\s+)?(?:("+ordinal+")\\s+)?("+unidades+"|"+formatos+")\\b(?:\\s+(m[aá]s\\s+(?:recientes?|antigu[oa]s?|viej[oa]s?)))?", "iu");
    const cambioLista = new RegExp("^mejor\\s+(?:(?:los|las)\\s+)?("+numero+")\\s+(?:m[aá]s\\s+)?(recientes?|antigu[oa]s?|viej[oa]s?|"+ordinal+")$", "iu");
    const opcionesOrden = ["registro_desc","registro_asc"];
    const direccionLista = marca => /ultimo|reciente/.test(norm(marca)) ? opcionesOrden[0] : opcionesOrden[1];
    const valorCantidad = palabra => /^\d+$/.test(palabra) ? Number(palabra) : cantidades.findIndex(c=>norm(c)===norm(palabra));

    function evaluarCoherencia(texto, previo, opts, apoyo, plan) {
        const aviso = texto => ({tipo:"mensaje",texto});
        const hallazgo = (codigos,decision,propuesta) => ({codigos,decision,propuesta});
        const pet = limpiarPeticion(texto);
        const cambio = previo && limpio(pet).match(cambioLista);
        if (cambio) {
            const n = valorCantidad(cambio[1]);
            if (n<1 || n>20) return hallazgo(["limite_fuera_rango"],"explicar",aviso("Puedo mostrar entre 1 y 20 documentos."));
            return hallazgo(["orden_cantidad_contextual"],"corregir",{tipo:"buscar",correccion:true,dudas:[],filtros:{...previo,orden:direccionLista(cambio[2]),limite:String(n)}});
        }
        if (plan.tipo!=="buscar" || plan.correccion) return null;
        const titulo = referenciaTitulo(pet);
        const exterior = titulo?.resto ?? pet;
        const filtroNegado = [plan.filtros.departamento,plan.filtros.categoria].some(valor=>
            valor && ["sin ","no incluir ","no incluyas "].some(marca=>limpio(exterior).includes(marca+norm(valor))));
        if (filtroNegado || exclusion.test(limpio(exterior)) || negacionAccion.test(limpio(exterior))) {
            return hallazgo(["restriccion_negada"],"aclarar",aviso("Indica qué criterio sí quieres incluir en la búsqueda."));
        }
        if (titulo?.valor && plan.filtros.buscar !== titulo.valor) {
            return hallazgo(["literal_alterado"],"aclarar",aviso("El título no se pudo conservar completo. Indica un título o folio más corto."));
        }
        const extension = /\b(?:en formato|(?:con |de )?extensi[oó]n)\s+\.?([a-z0-9]{1,8})\b/iu;
        const limitacionFormato = () => hallazgo(["extension_no_admitida"],"explicar",aviso("La búsqueda del chat no filtra por extensión. Puedes buscar por título, departamento o fecha."));
        if (extension.test(exterior)) return limitacionFormato();
        if (plan.filtros.orden && /\b(?:no|nunca|excepto|sin)\s+(?:(?:los|las|el|la)\s+)?(?:m[aá]s\s+)?(?:recientes?|antigu[oa]s?|viej[oa]s?|[uú]ltim[oa]s?|primer[oa]s?)\b/iu.test(exterior)) {
            return hallazgo(["orden_negado"],"aclarar",aviso("Indica qué orden sí quieres usar en la búsqueda."));
        }
        const lista = pet.match(cabeceraLista);
        if (!lista) return null;
        const [,primera,cantidad,segunda,unidad,ultima] = lista;
        const formato = new RegExp("^(?:"+formatos+")$","iu").test(unidad);
        if (formato && !(titulo?.literal && pet.startsWith(titulo.literal))) return limitacionFormato();
        let resto = pet.slice(lista[0].length);
        const alternativa = ultima && resto.match(/^\s+(?:o|y)\s+(?:(?:los|las)\s+)?(?:m[aá]s\s+)?(recientes?|antigu[oa]s?|viej[oa]s?)\b/iu);
        if (alternativa) resto = resto.slice(alternativa[0].length);
        const direcciones = [...new Set([primera,segunda,ultima,alternativa?.[1]].filter(Boolean).map(direccionLista))];
        const limites = cantidad ? [...new Set(cantidad.split(/\s+(?:o|u)\s+/iu).map(valorCantidad))] : [];
        const codigos = [];
        if (direcciones.length>1) codigos.push("orden_contradictorio");
        if (limites.length>1) codigos.push("cantidad_alternativa");
        if (limites.length===1 && String(limites[0])!==plan.filtros.limite) codigos.push("cantidad_perdida");
        if (!titulo && plan.filtros.buscar && [primera,segunda,ultima,cantidad].filter(Boolean).some(m=>(" "+norm(plan.filtros.buscar)+" ").includes(" "+norm(m)+" "))) codigos.push("texto_residual");
        if (!codigos.length) return null;
        if (limites.some(n=>n<1 || n>20)) return hallazgo(codigos,"explicar",aviso("Puedo mostrar entre 1 y 20 documentos. Indica una cantidad en ese intervalo."));
        // Reinterpreta solo el contenido restante, conservando su grafía y los criterios externos.
        const baseLista = (direcciones.length ? "últimos " : "") + unidad + resto;
        const limpioLista = criterios(baseLista,opts,apoyo);
        if (limpioLista.tipo==="mensaje") return hallazgo(codigos,"aclarar",limpioLista);
        const filtros = {...limpioLista.filtros};
        delete filtros.orden;
        delete filtros.limite;
        const dudas = [];
        if (direcciones.length===1) filtros.orden=direcciones[0];
        if (limites.length===1) filtros.limite=String(limites[0]);
        else if (!limites.length && plan.filtros.limite) filtros.limite=plan.filtros.limite;
        if (direcciones.length>1 || (!direcciones.length && !Object.keys(filtros).some(k=>k!=="limite"))) dudas.push({tipo:"orden",opciones:opcionesOrden});
        if (limites.length>1) dudas.push({tipo:"limite",opciones:limites.map(String)});
        dudas.push(...limpioLista.dudas);
        return hallazgo(codigos,dudas.length?"aclarar":"corregir",{...limpioLista,tipo:"buscar",correccion:false,filtros,dudas});
    }

    function validar(texto,previo,opts,apoyo,plan,activo,registrar) {
        const reloj=()=>root.performance?.now() ?? Date.now();
        const inicio=reloj();
        const h=evaluarCoherencia(texto,previo,opts,apoyo,plan);
        registrar?.({tipo:plan.tipo,codigos:h?.codigos || [],decision:h?.decision || "continuar",ms:reloj()-inicio});
        return activo && h ? h.propuesta : plan;
    }
    function elegirLista(duda,respuesta) {
        const palabra=limpio(respuesta).replace(/^(?:los|las)\s+/,"");
        if (duda.tipo==="limite") {
            const limite=String(valorCantidad(palabra));
            return duda.opciones.includes(limite)?{limite}:null;
        }
        if (/^(?:mas )?(?:recientes?|antigu[oa]s?|viej[oa]s?|ultim[oa]s?|primer[oa]s?)$/.test(palabra)) {
            const orden=direccionLista(palabra);
            return duda.opciones.includes(orden)?{orden}:null;
        }
        return null;
    }
    root.sigedPlanClippy={resolver,fechaLocal,limpiarPeticion,validar,elegirLista};
})(globalThis);

