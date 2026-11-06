// Reglas anteriores a la separación, para comparación de regresión.
function interpreteAnterior(categorias, areas) {
    const normalizar = texto => texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
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

    return interpretar;
}
module.exports = interpreteAnterior;
