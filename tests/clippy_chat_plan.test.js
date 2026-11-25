const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const raiz = {};
raiz.window = raiz;
vm.createContext(raiz);
for (const archivo of ["interprete_busqueda", "interprete_contextual", "clasificador_ayuda_clippy", "catalogo_ayuda_clippy", "clippy_chat_plan"]) {
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../app/static", archivo + ".js"), "utf8"), raiz);
}
const textoAyuda = tema => raiz.sigedConsultarAyuda(tema, {pantalla:"inicio", capacidades:{ver:true}});
const opciones = {
    areas:["Tesorería", "Obras Públicas", "Recursos Humanos", "Archivos"],
    categorias:["Informes", "Contratos", "Actas", "Inventarios", "Otros"],
    detallar:raiz.sigedInterpretarBusqueda.detallar,
    contextual:raiz.sigedInterpretarContexto,
    clasificar:raiz.sigedClasificarAyuda,
    ayudaValida:tema=>textoAyuda(tema)!==textoAyuda("")
};
const anterior = {departamento:"Obras Públicas",categoria:"Actas",desde:"2024-02-01",hasta:"2024-02-29"};
const resolver = (texto, contexto=null, apoyo=null) =>
    JSON.parse(JSON.stringify(raiz.sigedPlanClippy.resolver(texto,contexto,opciones,apoyo)));

test("ordinales, cantidades y alta conservan los criterios explícitos", () => {
    for (const [texto, orden, limite, extra] of [
        ["Busca el último documento subido","registro_desc","1",{}],
        ["Busca el documento más reciente que se haya subido al gestor","registro_desc","1",{}],
        ["Muéstrame los últimos 5 documentos registrados","registro_desc","5",{}],
        ["¿Cuál fue el primer documento que se subió?","registro_asc","1",{}],
        ["Lista los últimos tres documentos","registro_desc","3",{}],
        ["Busca los 3 informes más recientes de Tesorería","registro_desc","3",{categoria:"Informes",departamento:"Tesorería"}],
        ["Busca los dos contratos más antiguos","registro_asc","2",{categoria:"Contratos"}],
        ["Busca los primeros 5 documentos registrados","registro_asc","5",{}],
        ["Busca el último informe de Tesorería","registro_desc","1",{categoria:"Informes",departamento:"Tesorería"}],
    ]) assert.deepEqual(resolver(texto).filtros,{orden,limite,...extra},texto);
    assert.equal(resolver("Busca los 25 documentos más recientes").tipo,"mensaje");
    assert.deepEqual(resolver("Busca por favor los documentos de Tesorería").filtros,{departamento:"Tesorería"});
    assert.deepEqual(resolver("Necesito el documento que habla sobre los impactos de la inteligencia artificial").filtros,{buscar:"impactos inteligencia artificial"});
    assert.equal(resolver("Localiza el archivo que tenga la palabra prueba en su nombre").tipo,"mensaje");
    assert.equal(resolver("Encuentra el PDF más viejo").tipo,"mensaje");
    assert.deepEqual(resolver("Busca «Últimos 5 documentos registrados»").filtros,{buscar:"Últimos 5 documentos registrados"});
});

test("el objeto y la explicación pedida prevalecen sobre el verbo de localización", () => {
    for (const frase of ["Busca cómo cambio el tema de la pantalla", "Ubica la opción de modo oscuro",
        "Encuentra el apartado de ajustes", "Localiza el menú de preferencias"]) {
        assert.deepEqual(resolver(frase), {tipo:"ayuda",tema:"ajustes"}, frase);
    }
    for (const frase of ["Localiza el botón para cambiar la apariencia", "Encuentra la opción para personalizar la apariencia"]) {
        assert.equal(resolver(frase).consultar_modelo, true, frase);
        assert.deepEqual(resolver(frase, null, {intencion:"ajustes",analisis:{estado:"aceptada"}}),
            {tipo:"ayuda",tema:"ajustes"}, frase);
    }
    assert.deepEqual(resolver("Quiero descargar un PDF, pero primero explícame cómo se hace"),
        {tipo:"ayuda",tema:"descargar"});
    assert.equal(resolver("Busca el manual «Cómo cambio el tema»").tipo,"buscar");
});

test("una intención aceptada orienta ayuda sin exigir una pregunta formal", () => {
    const frase = "Me gustaría elegir la apariencia de la plataforma";
    assert.equal(resolver(frase).consultar_modelo,true);
    assert.deepEqual(resolver(frase,null,{intencion:"ajustes",analisis:{estado:"aceptada"}}), {tipo:"ayuda",tema:"ajustes"});
    assert.equal(resolver(frase,null,{intencion:"ajustes",analisis:{estado:"abstencion"}}).tipo,"mensaje");
    assert.equal(resolver("La mesa quedó afuera",null,{intencion:"busqueda_documental"}).tipo,"mensaje");
});

test("la extracción conserva folios y áreas aunque MiniLM se abstenga", () => {
    const apoyo = {criterios:{departamento:"Tesorería"},enlaces:[{tipo:"folio",valor:"TES-2025-42"}],
        consumir:{departamento:"Tesorería"},analisis:{estado:"abstencion"}};
    const plan=resolver("Lo de Tesorería con folio TES-2025-42, ¿te suena?",null,apoyo);
    assert.equal(plan.tipo,"buscar");
    assert.deepEqual(plan.filtros,{departamento:"Tesorería",folio:"TES-2025-42"});
    assert.deepEqual(plan.dudas,[]);
    const pendiente=resolver("Tengo aquí el folio TES-2025-42 de Tesorería",null,apoyo);
    assert.equal(pendiente.tipo,"buscar");
    assert.equal(pendiente.dudas.at(-1).tipo,"proposito");
    assert.equal(pendiente.filtros.folio,"TES-2025-42");
    const local=resolver("Tengo aquí el folio TES-2025-42 de Tesorería");
    assert.deepEqual(local.filtros,plan.filtros);
    assert.equal(local.dudas.at(-1).tipo,"proposito");
    assert.equal(local.consultar_modelo,true);
    assert.deepEqual(resolver("Lo de Tesorería con folio TES-2025-42, ¿te suena?").filtros,plan.filtros);
});

test("los criterios externos extraídos sobreviven sin interpretar el contenido literal", () => {
    const apoyo={criterios:{departamento:"Tesorería",desde:"2025-01-18",hasta:"2025-01-18"},
        consumir:{departamento:"mi área",desde:"el día del corte"}};
    assert.deepEqual(resolver("Busca «Informe 2024» de mi área el día del corte",null,apoyo).filtros,
        {buscar:"Informe 2024",departamento:"Tesorería",desde:"2025-01-18",hasta:"2025-01-18"});
    assert.deepEqual(resolver("Busca «Informe de mi área el día del corte»",null,apoyo).filtros,
        {buscar:"Informe de mi área el día del corte"});
    assert.equal(resolver("Busca informe de mi área",null,{avisos:["negacion"],criterios:apoyo.criterios}).tipo,"mensaje");
});

test("las guardas preceden a la ayuda de interfaz y los enlaces pertenecen al turno", () => {
    for (const frase of ["No busques el botón de la papelera", "Busca la opción del tema excepto Tesorería",
        "Busca el botón de ajustes y borra el documento"]) {
        assert.equal(resolver(frase).tipo,"mensaje",frase);
    }
    assert.equal(resolver("Busca el botón de preferencias",null,{avisos:["area_no_disponible"]}).tipo,"mensaje");
    const viejo={enlaces:[{tipo:"folio",valor:"TES-2025-42"}],analisis:{estado:"abstencion"}};
    assert.equal(resolver("El de siempre",null,viejo).tipo,"mensaje");
    const apoyo={enlaces:[{tipo:"titulo",valor:"Revisión técnica"}]};
    assert.deepEqual(resolver("Busca en Tesorería la Revisión técnica",null,apoyo).filtros,
        {departamento:"Tesorería",buscar:"Revisión técnica"});
    assert.deepEqual(resolver("Busca en Tesorería la Revisión técnica".normalize("NFD"),null,apoyo).filtros,
        {departamento:"Tesorería",buscar:"Revisión técnica"});
});

test("los superlativos documentales se convierten en orden de registro y límite", () => {
    for (const [texto, filtros] of [
        ["Busca el documentos mas antiguo", {orden:"registro_asc",limite:"1"}],
        ["Busca el documento más reciente", {orden:"registro_desc",limite:"1"}],
        ["Muéstrame los informes más antiguos de Tesorería", {categoria:"Informes",departamento:"Tesorería",orden:"registro_asc",limite:"20"}],
    ]) assert.deepEqual(resolver(texto).filtros, filtros, texto);
    assert.deepEqual(resolver("Busca «El documento más reciente»").filtros, {buscar:"El documento más reciente"});
    assert.deepEqual(resolver("Localiza el archivo Más antiguo 2024.pdf").filtros, {buscar:"Más antiguo 2024.pdf"});
    assert.equal(resolver("No busques el documento más antiguo").tipo, "mensaje");
});

test("las decisiones locales claras omiten MiniLM y las pendientes permiten consultarlo", () => {
    const requiere = texto => Boolean(resolver(texto).consultar_modelo);
    for (const texto of ["Busca las actas de 2025", "Localiza «Manual anual 2024.pdf»",
        "¿Cómo cierro mi sesión?", "Nunca descargues el contrato, solo dime cómo verlo",
        "Busca contratos excepto Tesorería", "Nueva conversación", "Muéstrame las actas de antier",
        "Cambia el folio al ACT-2025-02"]) {
        assert.equal(requiere(texto), false, texto);
    }
    assert.equal(requiere("¿En qué parte se elige la apariencia de las pantallas?"), true);
});

test("limpia peticiones de lectura sin reintroducir la frase cuando no quedan criterios", () => {
    for (const apoyo of [null, {intencion:"busqueda_documental"}]) {
        for (const [texto, filtros] of [
            ["Porfa, ¿me muestras los informes de pavimentación?", {categoria:"Informes", buscar:"pavimentacion"}],
            ["Tráeme el fichero de mantenimiento", {buscar:"mantenimiento"}],
            ["Encuentra los documentos en la categoría Actas", {categoria:"Actas"}],
            ["Ubica los inventarios con fecha 21 de enero de 2025", {categoria:"Inventarios", desde:"2025-01-21", hasta:"2025-01-21"}],
        ]) assert.deepEqual(resolver(texto, null, apoyo).filtros, filtros, texto);
        for (const texto of ["Busca", "Busca archivos", "Encuentra %%%", "¿Me enseñas el documento?"]) {
            assert.equal(resolver(texto, null, apoyo).tipo, "mensaje", texto);
        }
    }
});

test("una exclusión o una operación negada no se convierte en una búsqueda positiva", () => {
    for (const apoyo of [null, {intencion:"busqueda_documental", criterios:{departamento:"Tesorería"}}]) {
        for (const texto of ["Jamás abras el oficio RH-2025-123", "Nunca descargues el contrato", "No me traigas las actas",
            "Busca los informes salvo los del área de Archivos", "Muéstrame contratos sin incluir los de Tesorería",
            "Busca «Reporte 2024.xlsx» excepto en Tesorería"]) {
            assert.equal(resolver(texto, anterior, apoyo).tipo, "mensaje", texto);
        }
        assert.deepEqual(resolver("No abras el informe, nada más dime cómo verlo", anterior, apoyo),
            {tipo:"ayuda", tema:"documentos"});
        assert.deepEqual(resolver("Solo dime cómo abrirlo", anterior, apoyo), {tipo:"ayuda", tema:"documentos"});
        assert.deepEqual(resolver("Busca «Excepto el informe de Tesorería»", null, apoyo).filtros,
            {buscar:"Excepto el informe de Tesorería"});
    }
});

test("una frase desconocida requiere intención documental explícita aunque el modelo sugiera buscar", () => {
    for (const texto of ["La mesa quedó afuera", "Dame el pronóstico de Guadalajara", "Se me hizo tarde",
        "Mejor mañana vemos", "Traduce «Un verano caluroso»"]) {
        assert.equal(resolver(texto, null, {intencion:"busqueda_documental"}).tipo, "mensaje", texto);
    }
    assert.deepEqual(resolver("Busca archivos sobre prevención de incendios").filtros, {buscar:"prevencion incendios"});
    assert.deepEqual(resolver("Busca actas del departamento de Archivos").filtros, {categoria:"Actas", departamento:"Archivos"});
});

test("diferencia salida, acceso y vencimiento con MiniLM aceptado o en respaldo", () => {
    const ejemplos = [
        ["Oye, ¿cómo salgo de mi cuenta?", "cerrar_sesion", /menú lateral.*Cerrar sesión/],
        ["¿En dónde puedo terminar mi sesión?", "cerrar_sesion", /menú lateral.*Cerrar sesión/],
        ["¿Dónde está el cierre de sesión?", "cerrar_sesion", /menú lateral.*Cerrar sesión/],
        ["¿Dónde hago logout?", "cerrar_sesion", /menú lateral.*Cerrar sesión/],
        ["¿Qué debo hacer para iniciar mi sesión?", "iniciar_sesion", /pulsa Acceder/],
        ["Me marca que la sesión expiró. ¿Ahora qué?", "sesion", /recarga la página/],
        ["La sesión está vencida y no sé cómo volver a entrar", "sesion", /recarga la página/]
    ];
    for (const [frase, tema, texto] of ejemplos) {
        for (const apoyo of [null, {intencion:"sesion"}, {intencion:"inicio"}]) {
            const plan=resolver(frase, anterior, apoyo);
            assert.deepEqual(plan,{tipo:"ayuda",tema},frase);
            assert.match(textoAyuda(plan.tema),texto,frase);
        }
    }
});

test("una consulta general de sesión no presupone vencimiento", () => {
    const plan=resolver("¿Qué opciones de sesión tengo?");
    assert.deepEqual(plan,{tipo:"ayuda",tema:"sesion_general"});
    assert.doesNotMatch(textoAyuda(plan.tema), /sesión caducó/);
});

test("ubica documentos aunque MiniLM se abstenga o sugiera una intención distinta", () => {
    assert.deepEqual(resolver("¿En dónde quedó el informe de mantenimiento?").filtros,{buscar:"informe mantenimiento"});
    assert.deepEqual(resolver("Oye, ¿me podrías mostrar el contrato de vigilancia, porfa?").filtros,{buscar:"contrato vigilancia"});
    assert.deepEqual(resolver("¿Puedes buscar el archivo Resguardo-2024.docx?", anterior,{intencion:"subida"}).filtros,
        {buscar:"Resguardo-2024.docx"});
    assert.equal(resolver("Busca el manual «Cómo cerrar sesión»",{},{intencion:"sesion"}).tipo,"buscar");
});

test("conserva títulos, extensiones y años literales, y separa los filtros explícitos", () => {
    assert.deepEqual(resolver("Muéstrame el informe titulado «Programa 2024.pdf» de Tesorería").filtros,
        {departamento:"Tesorería",buscar:"Programa 2024.pdf"});
    assert.deepEqual(resolver("Busca el archivo Control Anual 2024.xlsx").filtros,{buscar:"Control Anual 2024.xlsx"});
    assert.deepEqual(resolver("Ahora es 2025.pdf").filtros,{buscar:"Ahora es 2025.pdf"});
    assert.deepEqual(resolver("Busca el archivo «Contratos 2025» de la categoría Otros").filtros,{categoria:"Otros",buscar:"Contratos 2025"});
    assert.deepEqual(resolver("Encuentra el archivo de la categoría Informes «Plan 2025.pdf»").filtros,
        {categoria:"Informes",buscar:"Plan 2025.pdf"});
    assert.deepEqual(resolver("Localiza el folio RH-2024-18 de Tesorería").filtros,
        {departamento:"Tesorería",folio:"RH-2024-18"});
    assert.deepEqual(resolver("Busca el registro interno #123").filtros,{registro:"123"});
    assert.deepEqual(resolver("¿Contratos de 2025?").filtros,{categoria:"Contratos",desde:"2025-01-01",hasta:"2025-12-31"});
});

test("solicitudes ambiguas no acaban en SQL por defecto", () => {
    for (const frase of ["¿Cómo le hago?", "Resuelve lo de ayer", "¿Por qué se quedó así?", "¿Cómo subir y buscar documentos?"]) {
        assert.equal(resolver(frase,anterior).tipo,"mensaje",frase);
    }
    assert.deepEqual(resolver("¿Por qué no aparece el documento?"),{tipo:"diagnostico",tema:"documento"});
});

test("una búsqueda nueva no hereda filtros y una corrección explícita sí", () => {
    assert.deepEqual(resolver("Busca contratos",anterior).filtros,{categoria:"Contratos"});
    assert.deepEqual(resolver("Mejor de Tesorería",anterior).filtros,{...anterior,departamento:"Tesorería"});
    assert.equal(resolver("Mejor de Tesorería").tipo,"mensaje");
    assert.equal(resolver("Nueva conversación",anterior).tipo,"reiniciar");
    assert.deepEqual(resolver("Nueva búsqueda: Busca contratos",anterior).filtros,{categoria:"Contratos"});
    assert.deepEqual(resolver("Cambia el folio al OF-2026-21", {folio:"RH-2025-87", categoria:"Actas"}).filtros,
        {folio:"OF-2026-21", categoria:"Actas"});
    assert.deepEqual(resolver("Cambia el área a Archivos", anterior).filtros, {...anterior,departamento:"Archivos"});
    assert.deepEqual(resolver("Ficha 245").filtros, {registro:"245"});
    assert.equal(resolver("EXP-2025-000123").expediente, "exp-2025-000123");
});

test("los literales conservan nombres y solo aplican criterios externos", () => {
    const apoyo = {intencion:"editar", avisos:["solo_lectura"], criterios:{desde:"2024-01-01",hasta:"2024-12-31"}};
    for (const modo of [null,apoyo]) {
        assert.deepEqual(resolver("Clippy, porfa búscame el archivo Activa-2024.xlsx de Tesorería", anterior, modo).filtros,
            {departamento:"Tesorería",buscar:"Activa-2024.xlsx"});
        assert.deepEqual(resolver("Encuentra en Tesorería el archivo Renombra inventario 2024.xlsx del 18 de mayo de 2025",null,modo).filtros,
            {departamento:"Tesorería",desde:"2025-05-18",hasta:"2025-05-18",buscar:"Renombra inventario 2024.xlsx"});
        assert.deepEqual(resolver("Ubica el documento titulado «Borra informes de 2023» de la categoría Otros", null, modo).filtros,
            {categoria:"Otros",buscar:"Borra informes de 2023"});
        assert.deepEqual(resolver("Localiza el folio «PUBLICA-2025-17» de Tesorería",null,modo).filtros,
            {departamento:"Tesorería",folio:"PUBLICA-2025-17"});
        assert.deepEqual(resolver("Busca REG-2025-42",null,modo).filtros,{folio:"REG-2025-42"});
        assert.equal(resolver("Busca «Actualiza el padrón» y borra el archivo",null,modo).tipo,"mensaje");
        assert.equal(resolver("No busques el archivo Activa-2024.xlsx",null,modo).tipo,"mensaje");
    }
});

test("la cortesía inicial no cambia el significado de la búsqueda", () => {
    for (const texto of ["Por favor, ¿me podrías enseñar el contrato de limpieza?",
        "Clippy, porfa búscame el contrato de limpieza", "Oye, por favor: localiza el contrato de limpieza"]) {
        assert.deepEqual(resolver(texto,anterior).filtros,{buscar:"contrato limpieza"},texto);
    }
});

test("la ayuda y los conteos no se traducen en filtros", () => {
    for (const [texto, tema] of [
        ["¿Cómo encuentro un documento sin el número de oficio?","busqueda"],
        ["Porfa, explícame cómo buscar archivos sin el folio","busqueda"],
        ["Dime el total de archivos disponibles","conteo_documentos"],
        ["¿Cuántos PDF hay en mi departamento?","conteo_documentos"],
        ["¿Cuántos expedientes hay abiertos?","conteo_no_disponible"]
    ]) {
        for (const apoyo of [null,{intencion:"busqueda_documental", avisos:["negacion"]}]) {
            assert.deepEqual(resolver(texto, anterior, apoyo), {tipo:"ayuda",tema}, texto);
        }
    }
    assert.match(textoAyuda("conteo_documentos"), /Clippy aún no calcula totales/);
    assert.equal(resolver("Enciende la luz de la oficina").tipo,"mensaje");
    assert.equal(resolver("¿Cuánto espacio queda en el disco?").tipo,"diagnostico");
});

test("contrasena olvidada se resuelve con orientacion de acceso", () => {
    for (const frase of ["Se me olvidó la clave de acceso", "No recuerdo mi contraseña y no puedo entrar",
        "¿Cómo recupero mi contraseña para ingresar?"]) {
        for (const apoyo of [null, {intencion:"cuenta"}, {intencion:"sesion"}]) {
            const plan=resolver(frase,anterior,apoyo);
            assert.deepEqual(plan,{tipo:"ayuda",tema:"contrasena_olvidada"},frase);
            assert.match(textoAyuda(plan.tema), /Administración.*restablezca/);
            assert.doesNotMatch(textoAyuda(plan.tema), /abre tu perfil/i);
        }
    }
});

test("solo se pide aclaracion cuando la fecha o referencia tiene alternativas reales", () => {
    const lista=resolver("Busca contratos del 06/06/2025", null,{intencion:"busqueda_documental"});
    assert.deepEqual(lista.filtros, {categoria:"Contratos",desde:"2025-06-06",hasta:"2025-06-06"});
    assert.deepEqual(lista.dudas,[]);
    const ambigua=resolver("Busca actas del 06/07/2025");
    assert.deepEqual(ambigua.dudas,[{tipo:"fecha_numerica",opciones:["2025-07-06","2025-06-07"]}]);
    assert.equal(ambigua.filtros.desde,undefined);
    assert.equal(resolver("Busca «Informe» y «Acta»").tipo,"mensaje");
    assert.equal(resolver("Busca folio AA-2025-18 y folio BB-2025-19").tipo,"mensaje");
});


test("observación conserva exactamente el plan y registra solo datos técnicos", () => {
    for (const [texto, codigo] of [
        ["Busca los últimos 3 documentos más antiguos","orden_contradictorio"],
        ["Busca dos o tres informes más recientes","cantidad_alternativa"],
        ["Busca los 3 PDF más antiguos","extension_no_admitida"],
        ["Mejor los dos más antiguos","orden_cantidad_contextual"],
        ["Busca «Últimos tres informes»",null],
    ]) {
        const p=resolver(texto,anterior);
        const antes=JSON.stringify(p);
        let datos;
        const salida=raiz.sigedPlanClippy.validar(texto,anterior,opciones,null,p,false,d=>datos=d);
        assert.strictEqual(salida,p);
        assert.equal(JSON.stringify(p),antes);
        assert.deepEqual(Object.keys(datos).sort(),["codigos","decision","ms","tipo"]);
        if (codigo) assert.ok(datos.codigos.includes(codigo),texto);
        else assert.equal(datos.codigos.length,0);
    }
});

test("validación activa conserva criterios y bloquea la consulta hasta resolver la duda", () => {
    const validar=(t,prev=null)=>JSON.parse(JSON.stringify(raiz.sigedPlanClippy.validar(t,prev,opciones,null,resolver(t,prev),true)));
    for (const frase of ["Busca los últimos 3 informes más antiguos de Tesorería","Muéstrame los primeros tres informes más recientes de Tesorería"]) {
        const p=validar(frase);
        assert.deepEqual(p.filtros,{categoria:"Informes",departamento:"Tesorería",limite:"3"});
        assert.deepEqual(p.dudas,[{tipo:"orden",opciones:["registro_desc","registro_asc"]}]);
        assert.ok(!p.consultar_modelo);
    }
    for (const [marca,orden] of [["recientes","registro_desc"],["antiguos","registro_asc"]]) {
        const p=validar("Busca dos o tres informes más "+marca+" de Tesorería");
        assert.deepEqual(p.filtros,{categoria:"Informes",departamento:"Tesorería",orden});
        assert.deepEqual(p.dudas,[{tipo:"limite",opciones:["2","3"]}]);
        const prev=validar("Muéstrame los cinco informes más recientes de Tesorería").filtros;
        const corregido=validar("Mejor los dos más "+marca,prev);
        assert.deepEqual(corregido.filtros,{...prev,orden,limite:"2"});
        assert.equal(corregido.correccion,true);
        assert.deepEqual(prev,{categoria:"Informes",departamento:"Tesorería",orden:"registro_desc",limite:"5"});
        assert.equal(validar("Busca los 3 PDF más "+marca).tipo,"mensaje");
    }
    assert.deepEqual(validar("Busca dos o tres informes").dudas,[{tipo:"limite",opciones:["2","3"]}]);
    assert.deepEqual(validar("Busca dos informes de Tesorería").filtros,{categoria:"Informes",departamento:"Tesorería",limite:"2"});
    assert.deepEqual(validar("Busca «Dos o tres informes más antiguos»").filtros,{buscar:"Dos o tres informes más antiguos"});
    assert.deepEqual(validar("Busca Reporte.pdf").filtros,{buscar:"Reporte.pdf"});
    assert.equal(validar("Busca tres informes excepto Tesorería").tipo,"mensaje");
    assert.equal(validar("Busca los 3 informes sin Tesorería").tipo,"mensaje");
    assert.equal(validar("Mejor dos antiguos").tipo,"mensaje");
    assert.deepEqual(validar("Busca los 3 informes más antiguos o más recientes de Tesorería").dudas,[{tipo:"orden",opciones:["registro_desc","registro_asc"]}]);
    assert.equal(validar("Busca tres documentos más recientes, no los más antiguos").tipo,"mensaje");
    assert.equal(validar("Busca los tres informes en formato PDF").tipo,"mensaje");
    assert.deepEqual(validar("Busca «Informe en formato PDF»").filtros,{buscar:"Informe en formato PDF"});
    assert.deepEqual(validar("Busca los primeros 3 documentos más recientes registrados").filtros,{limite:"3"});
    for (const respuesta of ["los más antiguos","Más recientes"]) {
        assert.ok(raiz.sigedPlanClippy.elegirLista({tipo:"orden",opciones:["registro_asc","registro_desc"]},respuesta));
    }
    assert.equal(raiz.sigedPlanClippy.elegirLista({tipo:"limite",opciones:["2","3"]},"cinco"),null);
});
