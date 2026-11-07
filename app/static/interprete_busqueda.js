// Reglas locales: proponen filtros, nunca consultan documentos ni autorizan accesos.
window.sigedInterpretarBusqueda = (() => {
    const normalizar = texto => texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
    const mesPatron = meses.join("|");
    const categoriasReglas = [
        [/\bcontratos?\b/g, "Contratos"], [/\bactas?\b/g, "Actas"],
        [/\bcertificados?\b/g, "Certificados"], [/\binformes?\b/g, "Informes"],
        [/\bbitacoras?\b/g, "Bitacoras"], [/\binventarios?\b/g, "Inventarios"]
    ];
    const formatos = fecha => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
    const fecha = (anio, mes, dia) => {
        const d = new Date(anio, mes, dia);
        return d.getFullYear() === anio && d.getMonth() === mes && d.getDate() === dia ? d : null;
    };
    const ultimoDia = (anio, mes) => new Date(anio, mes + 1, 0);
    const consumir = (texto, coincidencia) => texto.slice(0, coincidencia.index) + " " + texto.slice(coincidencia.index + coincidencia[0].length);

    function extraerFechas(texto, hoy) {
        let restante = texto;
        const avisos = [];
        const rangos = [];
        const dudas = [];
        function registrar(coincidencia, desde, hasta, problema) {
            restante = consumir(restante, coincidencia);
            if (problema || !desde || !hasta || desde > hasta) avisos.push(problema || "El intervalo de fechas no es válido; revísalo.");
            else rangos.push({ desde: formatos(desde), hasta: formatos(hasta) });
        }
        const anyo = "((?:19|20)\\d{2})";
        let m;
        // Rangos con días y año final: un año omitido requiere aclaración.
        const dias = new RegExp(`\\bentre\\s+(?:el\\s+)?(\\d{1,2})\\s+de\\s+(${mesPatron})\\s+(?:y|al)\\s+(?:el\\s+)?(\\d{1,2})\\s+de\\s+(${mesPatron})(?:\\s+(?:de\\s+)?${anyo})?\\b`);
        while ((m = dias.exec(restante))) {
            const y = m[5] ? Number(m[5]) : null;
            if (!y) dudas.push({tipo:"rango_sin_anio", inicio:{dia:Number(m[1]),mes:meses.indexOf(m[2])}, fin:{dia:Number(m[3]),mes:meses.indexOf(m[4])}});
            registrar(m, y && fecha(y, meses.indexOf(m[2]), Number(m[1])), y && fecha(y, meses.indexOf(m[4]), Number(m[3])), y ? null : "El intervalo no indica año; añádelo para filtrar por fechas.");
        }
        const rangoMeses = new RegExp(`\\b(?:de|desde)\\s+(${mesPatron})\\s+(?:a|hasta)\\s+(${mesPatron})(?:\\s+(?:de\\s+)?${anyo})?\\b`);
        while ((m = rangoMeses.exec(restante))) {
            const y = m[3] ? Number(m[3]) : null, a = meses.indexOf(m[1]), b = meses.indexOf(m[2]);
            if (!y) dudas.push({tipo:"rango_sin_anio", inicio:{dia:1,mes:a}, fin:{dia:null,mes:b}});
            registrar(m, y && fecha(y, a, 1), y && ultimoDia(y, b), y ? null : "El intervalo de meses no indica año; añádelo para filtrar por fechas.");
        }
        // ISO y día/mes/año; si ambos componentes son menores o iguales a 12 se pide aclaración.
        const numerica = /\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b|\b(\d{1,2})[\/.](\d{1,2})[\/.]((?:19|20)\d{2})\b/g;
        while ((m = numerica.exec(restante))) {
            let d, problema;
            if (m[1]) d = fecha(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
            else if (Number(m[4]) <= 12 && Number(m[5]) <= 12) {
                problema = "La fecha numérica es ambigua; elige su interpretación.";
                const primera = fecha(Number(m[6]), Number(m[5]) - 1, Number(m[4]));
                const segunda = fecha(Number(m[6]), Number(m[4]) - 1, Number(m[5]));
                const opciones = [...new Set([primera, segunda].filter(Boolean).map(formatos))];
                if (opciones.length > 1) dudas.push({tipo:"fecha_numerica", opciones});
            }
            else d = fecha(Number(m[6]), Number(m[5]) - 1, Number(m[4]));
            registrar(m, d, d, problema); numerica.lastIndex = 0;
        }
        const diaMes = new RegExp(`\\b(\\d{1,2})\\s+de\\s+(${mesPatron})\\s+(?:de\\s+)?${anyo}\\b`);
        while ((m = diaMes.exec(restante))) {
            const d = fecha(Number(m[3]), meses.indexOf(m[2]), Number(m[1])); registrar(m, d, d);
        }
        const mesRelativo = new RegExp(`\\b(${mesPatron})\\s+(?:(?:de|del)\\s+)?(este ano|ano pasado)\\b`);
        while ((m = mesRelativo.exec(restante))) {
            const y = hoy.getFullYear() - (m[2] === "ano pasado" ? 1 : 0), mes = meses.indexOf(m[1]);
            registrar(m, fecha(y, mes, 1), ultimoDia(y, mes));
        }
        const relativos = /\b(hoy|ayer|esta semana|semana pasada|este mes|mes pasado|este ano|ano pasado)\b/;
        while ((m = relativos.exec(restante))) {
            const y = hoy.getFullYear(), mes = hoy.getMonth(), dia = hoy.getDate();
            let inicio, fin;
            switch (m[1]) {
                case "hoy": inicio = fin = new Date(y, mes, dia); break;
                case "ayer": inicio = fin = new Date(y, mes, dia - 1); break;
                case "esta semana": case "semana pasada": {
                    const lunes = dia - ((hoy.getDay() + 6) % 7) - (m[1] === "semana pasada" ? 7 : 0);
                    inicio = new Date(y, mes, lunes); fin = new Date(y, mes, lunes + 6); break;
                }
                case "este mes": inicio = new Date(y, mes, 1); fin = ultimoDia(y, mes); break;
                case "mes pasado": inicio = new Date(y, mes - 1, 1); fin = new Date(y, mes, 0); break;
                case "este ano": inicio = new Date(y, 0, 1); fin = new Date(y, 11, 31); break;
                default: inicio = new Date(y - 1, 0, 1); fin = new Date(y - 1, 11, 31);
            }
            registrar(m, inicio, fin);
        }
        const mesAnio = new RegExp(`\\b(${mesPatron})\\s+(?:de\\s+)?${anyo}\\b`);
        while ((m = mesAnio.exec(restante))) {
            const y = Number(m[2]), mes = meses.indexOf(m[1]); registrar(m, fecha(y, mes, 1), ultimoDia(y, mes));
        }
        const mesSinAnio = new RegExp(`\\b(${mesPatron})\\b`);
        while ((m = mesSinAnio.exec(restante))) {
            dudas.push({tipo:"mes_sin_anio", mes:meses.indexOf(m[1]), nombre:m[1]});
            registrar(m, null, null, `No se indicó el año de ${m[1]}; añádelo para filtrar por fechas.`);
        }
        const anioSolo = /\b(?:19|20)\d{2}\b/;
        while ((m = anioSolo.exec(restante))) { const y = Number(m[0]); registrar(m, fecha(y, 0, 1), fecha(y, 11, 31)); }
        if (rangos.length > 1) {
            avisos.push("Hay varias referencias de fecha; aclara cuál intervalo deseas aplicar.");
            dudas.push({tipo:"fechas_multiples", opciones:rangos});
        }
        return { restante, fechas: rangos.length === 1 && !avisos.length ? rangos[0] : {}, avisos, dudas };
    }

    function detallar(entrada, categorias, areas) {
        const texto = normalizar(entrada.trim());
        let restante = texto;
        const filtros = {}, avisos = [], dudas = [];
        const expediente = texto.match(/\bexp[-/]\d{4}[-/]\d+\b/i);
        if (expediente) restante = consumir(restante, expediente);
        const oficio = restante.match(/\b(?:oficio|of\.|of(?=\s))\s*(?:numero|num\.?|no\.?)?\s*[:#-]?\s*((?=[a-z0-9\/-]*\d)[a-z0-9]+(?:[-\/][a-z0-9]+)*)/) ||
            restante.match(/\b(of-\d+(?:[-\/]\w+)*)\b/);
        if (oficio) { filtros.oficio = oficio[1]; restante = consumir(restante, oficio); }
        const nombres = areas.map(nombre => ({ nombre, texto: normalizar(nombre) }));
        // Solo alias institucionales inequívocos y presentes en el catálogo.
        const aliasArea = [[/\b(?:rr\.?\s*hh\.?|recursos humanos)\b/, "Recursos Humanos"], [/\b(?:obras publicas)\b/, "Obras Públicas"]];
        const encontrados = nombres.filter(area => new RegExp(`(?:^|[^\\p{L}\\p{N}])${area.texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=$|[^\\p{L}\\p{N}])`, "u").test(restante));
        for (const [regla, nombre] of aliasArea) if (areas.includes(nombre) && regla.test(restante) && !encontrados.some(a => a.nombre === nombre)) encontrados.push({nombre, texto: normalizar(nombre), regla});
        if (encontrados.length === 1) {
            filtros.departamento = encontrados[0].nombre;
            restante = restante.replace(encontrados[0].regla || encontrados[0].texto, " ");
        } else if (encontrados.length > 1) {
            avisos.push("Se mencionan varias áreas; elige el departamento manualmente.");
            dudas.push({tipo:"area", opciones:encontrados.map(area => area.nombre)});
            for (const area of encontrados) restante = restante.replace(area.regla || area.texto, " ");
            restante = restante.replace(/\b(?:y|o)\b/g, " ");
        }
        const detectadas = categoriasReglas.filter(([regla, nombre]) => categorias.includes(nombre) && new RegExp(regla.source).test(restante));
        if (detectadas.length === 1) { filtros.categoria = detectadas[0][1]; restante = restante.replace(detectadas[0][0], " "); }
        else if (detectadas.length > 1) {
            avisos.push("Se mencionan varias categorías; selecciona una manualmente.");
            dudas.push({tipo:"categoria", opciones:detectadas.map(([, nombre]) => nombre)});
            for (const [regla] of detectadas) restante = restante.replace(regla, " ");
            restante = restante.replace(/\b(?:y|o)\b/g, " ");
        }
        const rangoIncompleto = new RegExp(`\\b(?:de|desde)\\s+(${mesPatron})\\s+(?:a|hasta)\\s*$`).test(restante);
        const fechas = extraerFechas(restante, new Date()); restante = fechas.restante;
        if (rangoIncompleto) {
            fechas.dudas = fechas.dudas.filter(duda => duda.tipo !== "mes_sin_anio");
            fechas.dudas.unshift({tipo:"rango_incompleto"});
            fechas.avisos.unshift("El intervalo está incompleto; indica ambas fechas manualmente.");
            fechas.fechas = {};
        }
        if (fechas.avisos.length && !fechas.dudas.length) fechas.dudas.push({tipo:"fecha_manual"});
        Object.assign(filtros, fechas.fechas); avisos.push(...fechas.avisos); dudas.push(...fechas.dudas);
        if (!filtros.departamento && encontrados.length === 0 && areas.includes("Obras Públicas") && /\bobras\b/.test(restante)) {
            dudas.push({tipo:"obras", area:"Obras Públicas"});
            avisos.push("“Obras” podría ser el tema o el departamento; elige si deseas filtrar por área.");
        }
        if (fechas.avisos.length) restante = restante.replace(/\b(?:y|o|a|al)\b/g, " ");
        restante = restante.replace(/\b(?:quiero|encontrar|buscar|busca|busco|muestrame|dame|necesito|los|las|el|la|un|una|unos|unas|de|del|en|por|para|sobre|que|se|registrado|registrada|registrados|registradas|este|ano|pasado|documento|documentos|archivo|archivos|oficio|oficios|expediente|expedientes)\b/g, " ");
        const terminos = restante.replace(/[^\p{L}\p{N}\s-]/gu, " ").replace(/\s+/g, " ").trim();
        if (terminos) filtros.buscar = terminos.slice(0, 200);
        if (!Object.keys(filtros).length && texto && !avisos.length && !expediente) filtros.buscar = texto.slice(0, 200);
        return { filtros, avisos, expediente: expediente ? expediente[0] : null, dudas };
    }
    function interpretar(entrada, categorias, areas) { return detallar(entrada, categorias, areas).filtros; }
    interpretar.detallar = detallar;
    return interpretar;
})();
