import { enqueueSnackbar } from "notistack";
import { useEffect, useState } from "react";
import {
	type ActaOralDTO,
	descargarActaOralPdf,
	type GuardarActaOralPayload,
	guardarActaOral,
	listarActasOrales,
	obtenerActaOral,
	obtenerActaOralPdfBlob,
} from "@/api/cargaNotas";
import type {
	OralActFormTopic,
	OralActFormValues,
} from "@/components/secretaria/OralExamActaDialog";
import type { OralTopicScore } from "@/utils/actaOralPdf";
import { getErrorStatus } from "@/utils/errors";
import type { FinalRowState } from "../types";

const createTopicRow = (
	tema = "",
	score?: string | null,
): OralActFormTopic => ({
	id: `${Date.now()}-${Math.random()}`,
	tema,
	score: (score as OralTopicScore | "") || "",
});

const ensureTopicRowsFromApi = (
	topics: ActaOralDTO["temas_estudiante"] | undefined,
	min: number,
): OralActFormTopic[] => {
	const rows = (topics ?? []).map((item) =>
		createTopicRow(item.tema ?? "", item.score ?? null),
	);
	while (rows.length < min) {
		rows.push(createTopicRow());
	}
	return rows;
};

function mapActaOralDtoToFormValues(dto: ActaOralDTO): OralActFormValues {
	return {
		actaNumero: dto.acta_numero ?? "",
		folioNumero: dto.folio_numero ?? "",
		fecha: dto.fecha ?? "",
		curso: dto.curso ?? "",
		notaFinal: dto.nota_final ?? "",
		observaciones: dto.observaciones ?? "",
		temasEstudiante: ensureTopicRowsFromApi(dto.temas_estudiante, 3),
		temasDocente: ensureTopicRowsFromApi(dto.temas_docente, 4),
	};
}

function mapFormValuesToOralPayload(
	values: OralActFormValues,
): GuardarActaOralPayload {
	const normalize = (rows: OralActFormTopic[]) =>
		rows
			.filter((row) => row.tema.trim())
			.map((row) => ({
				tema: row.tema.trim(),
				score: row.score || null,
			}));

	return {
		acta_numero: values.actaNumero || null,
		folio_numero: values.folioNumero || null,
		fecha: values.fecha || null,
		curso: values.curso || null,
		nota_final: values.notaFinal || null,
		observaciones: values.observaciones || null,
		temas_estudiante: normalize(values.temasEstudiante),
		temas_docente: normalize(values.temasDocente),
	};
}

export function useOralExamActa(
	finalSelectedMesaId: number | null,
	finalReadOnly: boolean,
) {
	const [oralActDrafts, setOralActDrafts] = useState<
		Record<number, OralActFormValues>
	>({});
	const [oralDialogRow, setOralDialogRow] = useState<FinalRowState | null>(
		null,
	);
	const [oralActaLoading, setOralActaLoading] = useState(false);
	const [oralActaSaving, setOralActaSaving] = useState(false);
	const [downloadingOralBatch, setDownloadingOralBatch] = useState(false);
	const [selectedOralIds, setSelectedOralIds] = useState<Set<number>>(
		new Set(),
	);

	useEffect(() => {
		setOralActDrafts({});
		setOralDialogRow(null);
		setSelectedOralIds(new Set());
	}, [finalSelectedMesaId]);

	const toggleOralSelection = (inscripcionId: number) => {
		setSelectedOralIds((prev) => {
			const next = new Set(prev);
			if (next.has(inscripcionId)) {
				next.delete(inscripcionId);
			} else {
				next.add(inscripcionId);
			}
			return next;
		});
	};

	const handleOpenOralActa = async (row: FinalRowState) => {
		if (finalReadOnly) {
			enqueueSnackbar(
				"Solo los docentes del tribunal pueden gestionar las actas orales de esta mesa.",
				{ variant: "warning" },
			);
			return;
		}
		if (!finalSelectedMesaId) {
			enqueueSnackbar("Selecciona una mesa para generar el acta oral.", {
				variant: "warning",
			});
			return;
		}
		setOralDialogRow(row);
		if (oralActDrafts[row.inscripcionId]) {
			return;
		}
		setOralActaLoading(true);
		try {
			const data = await obtenerActaOral(
				finalSelectedMesaId,
				row.inscripcionId,
			);
			setOralActDrafts((prev) => ({
				...prev,
				[row.inscripcionId]: mapActaOralDtoToFormValues(data),
			}));
		} catch (error) {
			// 404 = el estudiante todavía no tiene acta oral cargada: se abre vacía,
			// sin cartel de error. El status se lee con getErrorStatus porque el
			// interceptor propaga un AppError, no el AxiosError original.
			if (getErrorStatus(error) !== 404) {
				enqueueSnackbar("No se pudo cargar el acta oral.", {
					variant: "error",
				});
			}
		} finally {
			setOralActaLoading(false);
		}
	};

	const handleCloseOralActa = () => {
		setOralDialogRow(null);
	};

	const handleSaveOralActa = async (values: OralActFormValues) => {
		if (!oralDialogRow || !finalSelectedMesaId) {
			enqueueSnackbar("Selecciona una mesa para registrar el acta oral.", {
				variant: "warning",
			});
			throw new Error("Mesa no seleccionada");
		}
		if (finalReadOnly) {
			enqueueSnackbar(
				"Solo los docentes del tribunal pueden registrar actas orales para esta mesa.",
				{ variant: "warning" },
			);
			throw new Error("Sin permisos");
		}
		setOralActaSaving(true);
		try {
			await guardarActaOral(
				finalSelectedMesaId,
				oralDialogRow.inscripcionId,
				mapFormValuesToOralPayload(values),
			);
			setOralActDrafts((prev) => ({
				...prev,
				[oralDialogRow.inscripcionId]: values,
			}));
			enqueueSnackbar("Acta oral guardada correctamente.", {
				variant: "success",
			});
		} catch (error) {
			enqueueSnackbar("No se pudo guardar el acta oral.", { variant: "error" });
			throw error;
		} finally {
			setOralActaSaving(false);
		}
	};

	const handleDownloadAllOralActas = async () => {
		// A diferencia de guardar/editar, descargar es de solo lectura: el
		// backend (_check_mesa_actas_access) es quien decide quién puede verla
		// (tribunal de esa mesa, admin/secretaría, staff con alcance de carrera,
		// títulos). No usamos acá finalReadOnly porque ese flag refleja permiso
		// de EDICIÓN de notas, no de descarga — títulos por ejemplo puede
		// descargar pero no editar.
		if (!finalSelectedMesaId) {
			enqueueSnackbar("Selecciona una mesa para descargar las actas orales.", {
				variant: "warning",
			});
			return;
		}
		setDownloadingOralBatch(true);
		try {
			const todasLasActas = await listarActasOrales(finalSelectedMesaId);
			if (!todasLasActas.length) {
				enqueueSnackbar("No hay actas orales registradas para esta mesa.", {
					variant: "info",
				});
				return;
			}
			// Si hay filas tildadas, se descarga solo esa selección; si no se
			// tildó nada, se descargan todas las actas de la mesa.
			const actas =
				selectedOralIds.size > 0
					? todasLasActas.filter((a) => selectedOralIds.has(a.inscripcion_id))
					: todasLasActas;

			if (!actas.length) {
				enqueueSnackbar(
					"Ninguna de las filas seleccionadas tiene acta oral registrada.",
					{ variant: "warning" },
				);
				return;
			}

			const withSafeName = actas.map((acta) => ({
				acta,
				safeName: acta.estudiante.replace(/\s+/g, "_").replace(/[^\w_-]/g, ""),
			}));

			if (withSafeName.length === 1) {
				// Una sola acta: descarga directa del PDF, sin ZIP.
				const { acta, safeName } = withSafeName[0];
				await descargarActaOralPdf(
					finalSelectedMesaId,
					acta.inscripcion_id,
					`acta_oral_${safeName}.pdf`,
				);
			} else {
				// Varias actas: se arman en un único ZIP para evitar que el
				// navegador bloquee descargas múltiples simultáneas.
				const JSZip = (await import("jszip")).default;
				const zip = new JSZip();
				for (const { acta, safeName } of withSafeName) {
					const blob = await obtenerActaOralPdfBlob(
						finalSelectedMesaId,
						acta.inscripcion_id,
					);
					zip.file(`acta_oral_${safeName}.pdf`, blob);
				}
				const zipBlob = await zip.generateAsync({ type: "blob" });
				const url = URL.createObjectURL(zipBlob);
				const a = document.createElement("a");
				a.href = url;
				a.download = `actas_orales_mesa_${finalSelectedMesaId}.zip`;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}
			enqueueSnackbar("Actas orales descargadas.", { variant: "success" });
		} catch (_error) {
			enqueueSnackbar("No se pudieron descargar las actas orales.", {
				variant: "error",
			});
		} finally {
			setDownloadingOralBatch(false);
		}
	};

	return {
		oralActDrafts,
		oralDialogRow,
		oralActaLoading,
		oralActaSaving,
		downloadingOralBatch,
		selectedOralIds,
		toggleOralSelection,
		handleOpenOralActa,
		handleCloseOralActa,
		handleSaveOralActa,
		handleDownloadAllOralActas,
		mapActaOralDtoToFormValues,
		mapFormValuesToOralPayload,
	};
}


