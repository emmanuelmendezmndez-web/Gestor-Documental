// Estado efímero: cada instancia vive solo en la página que la crea.
(() => {
    const LIMITES = Object.freeze({buscar: 200, categoria: 100, departamento: 100, oficio: 60, autor: 100, desde: 10, hasta: 10});
    const CAMPOS = Object.keys(LIMITES);
    const IDENTIFICADOR = /^[a-z0-9_-]{1,64}$/;
    const copiar = valor => JSON.parse(JSON.stringify(valor));

    function fechaValida(valor) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(valor)) return false;
        const [anio, mes, dia] = valor.split('-').map(Number);
        const fecha = new Date(0);
        fecha.setUTCFullYear(anio, mes - 1, dia);
        return anio >= 1 && fecha.getUTCFullYear() === anio && fecha.getUTCMonth() === mes - 1 && fecha.getUTCDate() === dia;
    }

    function validarFiltros(filtros) {
        if (!filtros || typeof filtros !== 'object' || Array.isArray(filtros)) throw new TypeError('Filtros inválidos');
        for (const [clave, valor] of Object.entries(filtros)) {
            if (!CAMPOS.includes(clave) || typeof valor !== 'string' || valor.length > LIMITES[clave]) throw new TypeError('Filtro inválido');
            if ((clave === 'desde' || clave === 'hasta') && valor && !fechaValida(valor)) throw new RangeError('Fecha inválida');
        }
        if (filtros.desde && filtros.hasta && filtros.desde > filtros.hasta) throw new RangeError('Intervalo inválido');
    }

    function crearMemoriaTemporal() {
        let estado = null;
        let ultimoValido = null;
        const exigirActiva = () => { if (!estado) throw new Error('No hay interacción activa'); };
        const confirmar = borrador => { validarFiltros(borrador.filtros); estado = borrador; ultimoValido = copiar(borrador); };
        const validarId = id => { if (typeof id !== 'string' || !IDENTIFICADOR.test(id)) throw new TypeError('Identificador inválido'); };

        function iniciar(consulta, intencion = 'documentos', filtros = {}) {
            if (estado) throw new Error('Ya hay una interacción activa');
            if (typeof consulta !== 'string' || consulta.length > 200) throw new TypeError('Consulta inválida');
            if (!['documentos', 'expedientes'].includes(intencion)) throw new TypeError('Intención inválida');
            validarFiltros(filtros);
            confirmar({consulta, intencion, filtros: copiar(filtros), manuales: [], pendientes: [], resueltas: []});
        }

        function consultar() { return estado ? copiar(estado) : null; }
        function obtenerUltimoValido() { return ultimoValido ? copiar(ultimoValido) : null; }

        function actualizar(cambios, origen = 'manual') {
            exigirActiva();
            if (!['manual', 'asistente'].includes(origen)) throw new TypeError('Origen inválido');
            validarFiltros(cambios);
            const nuevo = copiar(estado);
            for (const [clave, valor] of Object.entries(cambios)) {
                if (origen === 'asistente' && nuevo.manuales.includes(clave)) continue;
                if (valor === '') delete nuevo.filtros[clave]; else nuevo.filtros[clave] = valor;
                if (origen === 'manual' && !nuevo.manuales.includes(clave)) nuevo.manuales.push(clave);
            }
            confirmar(nuevo);
        }

        function quitar(clave, origen = 'manual') {
            if (!CAMPOS.includes(clave)) throw new TypeError('Filtro inválido');
            actualizar({[clave]: ''}, origen);
        }

        // Registrar la prioridad aun si el valor escrito es temporalmente inválido.
        function marcarManual(clave) {
            exigirActiva();
            if (!CAMPOS.includes(clave)) throw new TypeError('Filtro inválido');
            const nuevo = copiar(estado);
            if (!nuevo.manuales.includes(clave)) nuevo.manuales.push(clave);
            confirmar(nuevo);
        }

        function pendiente(id) {
            exigirActiva(); validarId(id);
            const nuevo = copiar(estado);
            if (!nuevo.pendientes.includes(id) && !nuevo.resueltas.some(item => item.id === id)) nuevo.pendientes.push(id);
            confirmar(nuevo);
        }

        function resolver(id, opcion, cambios = {}) {
            exigirActiva(); validarId(id); validarId(opcion); validarFiltros(cambios);
            if (!estado.pendientes.includes(id)) throw new Error('Aclaración inexistente');
            const nuevo = copiar(estado);
            for (const [clave, valor] of Object.entries(cambios)) {
                if (nuevo.manuales.includes(clave)) continue;
                if (valor === '') delete nuevo.filtros[clave]; else nuevo.filtros[clave] = valor;
            }
            nuevo.pendientes = nuevo.pendientes.filter(item => item !== id);
            nuevo.resueltas.push({id, opcion});
            confirmar(nuevo);
        }

        function descartar() { estado = null; ultimoValido = null; }
        return Object.freeze({iniciar, consultar, obtenerUltimoValido, actualizar, quitar, marcarManual, pendiente, resolver,
            reiniciar: descartar, cancelar: descartar, finalizar: descartar});
    }

    if (typeof module !== 'undefined' && module.exports) module.exports = crearMemoriaTemporal;
    else globalThis.crearMemoriaTemporal = crearMemoriaTemporal;
})();
