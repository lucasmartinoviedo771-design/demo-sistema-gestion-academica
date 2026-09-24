/**
 * Borrador local (localStorage) para formularios largos que pueden tardar
 * horas en completarse (ej. carga de un acta con muchos estudiantes).
 * Es una red de seguridad ante cortes de conexión / cierre accidental de la
 * pestaña — el guardado real sigue siendo el que hace el backend al enviar
 * el formulario. Nunca debe ser la única fuente de verdad de los datos.
 */

const PREFIX = "ipes6_draft_";
const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24hs: pasado eso, se descarta como obsoleto

type DraftEnvelope<T> = {
	savedAt: number;
	data: T;
};

function safeStorage(): Storage | null {
	try {
		const testKey = "__ipes6_draft_test__";
		window.localStorage.setItem(testKey, "1");
		window.localStorage.removeItem(testKey);
		return window.localStorage;
	} catch {
		return null;
	}
}

export function saveDraft<T>(key: string, data: T): void {
	const storage = safeStorage();
	if (!storage) return;
	try {
		const envelope: DraftEnvelope<T> = { savedAt: Date.now(), data };
		storage.setItem(PREFIX + key, JSON.stringify(envelope));
	} catch {
		// Cuota llena u otro error de storage: el borrador es solo una
		// conveniencia, no debe romper el flujo principal del formulario.
	}
}

export function loadDraft<T>(key: string): T | null {
	const storage = safeStorage();
	if (!storage) return null;
	try {
		const raw = storage.getItem(PREFIX + key);
		if (!raw) return null;
		const envelope = JSON.parse(raw) as DraftEnvelope<T>;
		if (!envelope || typeof envelope.savedAt !== "number") return null;
		if (Date.now() - envelope.savedAt > MAX_AGE_MS) {
			storage.removeItem(PREFIX + key);
			return null;
		}
		return envelope.data;
	} catch {
		return null;
	}
}

export function clearDraft(key: string): void {
	const storage = safeStorage();
	if (!storage) return;
	try {
		storage.removeItem(PREFIX + key);
	} catch {
		// no-op
	}
}
