const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// El formulario y fetch son dobles. El chat, el intérprete y el despacho son los reales.
function crearChat() {
    const eventos = new Map();
    const parrafos = [];
    const solicitudes = [];
    function nodo() {
        return {
            dataset:{}, append(){}, setAttribute(){}, removeAttribute(){},
            addEventListener(tipo,fn) { eventos.set(this, {...eventos.get(this), [tipo]:fn}); },
            querySelector() { return null; }
        };
    }
    const campo=nodo(), boton=nodo(), formulario=nodo();
    formulario.elements={texto:campo};
    formulario.querySelector=()=>boton;
    const dialogo=nodo();
    dialogo.querySelector=selector=>selector==="form"?formulario:nodo();
    const contexto={
        AbortController,URLSearchParams,setTimeout,clearTimeout,
        ResizeObserver:class { observe() {} },
        addEventListener(){}, sigedOpcionesBusqueda:{categorias:["Informes","Actas","Contratos"],areas:["Tesorería"]},
        document:{
            getElementById:id=>id==="chat-clippy"?dialogo:nodo(),
            querySelector:()=>null,
            createElement(tag) {
                const elemento=nodo();
                if (tag==="p") parrafos.push(elemento);
                return elemento;
            }
        },
        async fetch(ruta) {
            solicitudes.push(ruta);
            return {ok:true,json:async()=>({documentos:[]})};
        }
    };
    contexto.window=contexto;
    vm.createContext(contexto);
    for (const archivo of ["interprete_busqueda","interprete_contextual","clasificador_ayuda_clippy","catalogo_ayuda_clippy","clippy_chat_plan","clippy_chat"]) {
        vm.runInContext(fs.readFileSync(path.join(__dirname,"../app/static",archivo+".js"),"utf8"),contexto);
    }
    return {
        solicitudes,
        async decir(texto) {
            campo.value=texto;
            eventos.get(formulario).submit({preventDefault(){}});
            await new Promise(resolve=>setImmediate(resolve));
            return parrafos.at(-1).textContent;
        }
    };
}

const abril={desde:"2025-04-01",hasta:"2025-04-30"};
const lista={categoria:"Informes",orden:"registro_asc",limite:"2"};
for (const [nombre,ajustes,final,esperado] of [
    ["orden y cantidad",["Mejor los dos más antiguos"],"2025",{...lista,...abril}],
    ["solo cantidad",["Mejor solo tres"],"2025",{categoria:"Informes",limite:"3",...abril}],
    ["solo orden",["Los más recientes"],"2025",{categoria:"Informes",orden:"registro_desc",...abril}],
    ["dos cambios sucesivos",["Mejor los dos más antiguos","Mejor los más recientes"],"2025",{...lista,orden:"registro_desc",...abril}],
    ["fecha sustituida",["Mejor los dos más antiguos"],"Mejor mayo de 2024",{...lista,desde:"2024-05-01",hasta:"2024-05-31"}],
    ["fecha retirada",["Mejor los dos más antiguos"],"Quita la fecha",lista],
    ["búsqueda nueva",["Mejor los dos más antiguos"],"Busca contratos de Tesorería",{categoria:"Contratos",departamento:"Tesorería"}],
]) {
    test("aclaración de año con "+nombre,async()=>{
        const chat=crearChat();
        for (const turno of ["Busca informes de abril",...ajustes]) {
            assert.match(await chat.decir(turno),/de qué año/i);
            assert.deepEqual(chat.solicitudes,[]);
        }
        await chat.decir(final);
        assert.equal(chat.solicitudes.length,1);
        const url=new URL(chat.solicitudes[0],"http://localhost");
        assert.equal(url.pathname,"/asistente/documentos");
        assert.deepEqual(Object.fromEntries(url.searchParams),esperado);
    });
}

