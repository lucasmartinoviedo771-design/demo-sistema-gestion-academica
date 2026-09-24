import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import dayjs from "dayjs";
import { enqueueSnackbar } from "notistack";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
	guardarBorradorActaOral,
	obtenerBorradorActaOral,
} from "@/api/cargaNotas";
import { ORAL_SCORE_OPTIONS, type OralTopicScore } from "@/utils/actaOralPdf";
import { getErrorStatus } from "@/utils/errors";
import { clearDraft, loadDraft, saveDraft } from "@/utils/formDraft";

export type OralActFormTopic = {
	id: string;
	tema: string;
	score: OralTopicScore | "";
};

export type OralActFormValues = {
	actaNumero: string;
	folioNumero: string;
	fecha: string;
	curso: string;
	notaFinal: string;
	observaciones: string;
	temasEstudiante: OralActFormTopic[];
	temasDocente: OralActFormTopic[];
};

const scoreOptions = ORAL_SCORE_OPTIONS;
// Solo números de 1 a 10 — nada de texto libre ("8 (ocho)", etc). Antes se
// podía escribir cualquier cosa acá, lo que obligaba a parsear la nota con
// una regex más adelante (al sincronizarla con el acta final).
const NOTA_FINAL_OPTIONS = Array.from({ length: 10 }, (_, i) => String(i + 1));

const createTopicRow = (): OralActFormTopic => ({
	id: `${Date.now()}-${Math.random()}`,
	tema: "",
	score: "",
});

type TribunalInfo = {
	presidente?: string | null;
	vocal1?: string | null;
	vocal2?: string | null;
	vocalExtra?: string | null;
};

type OralExamActaDialogProps = {
	open: boolean;
	onClose: () => void;
	estudianteNombre: string;
	estudianteDni: string;
	carrera?: string | null;
	unidadCurricular?: string | null;
	curso?: string | null;
	fechaMesa?: string | null;
	tribunal?: TribunalInfo;
	existingValues?: OralActFormValues;
	defaultNota?: string | null;
	loading?: boolean;
	saving?: boolean;
	onSave: (values: OralActFormValues) => Promise<void>;
	mesaId?: number;
	inscripcionId?: number;
};

const ensureMinRows = (rows: OralActFormTopic[], min = 3) => {
	const clone = [...rows];
	while (clone.length < min) {
		clone.push(createTopicRow());
	}
	return clone;
};

const OralExamActaDialog: React.FC<OralExamActaDialogProps> = ({
	open,
	onClose,
	estudianteNombre,
	estudianteDni,
	carrera,
	unidadCurricular,
	curso,
	fechaMesa,
	tribunal,
	existingValues,
	defaultNota,
	loading = false,
	saving = false,
	onSave,
	mesaId,
	inscripcionId,
}) => {
	const [form, setForm] = useState<OralActFormValues>(() => ({
		actaNumero: "",
		folioNumero: "",
		fecha: fechaMesa
			? dayjs(fechaMesa).format("YYYY-MM-DD")
			: dayjs().format("YYYY-MM-DD"),
		curso: curso ?? "",
		notaFinal: defaultNota ?? "",
		observaciones: "",
		temasEstudiante: ensureMinRows([], 3),
		temasDocente: ensureMinRows([], 4),
	}));

	const [submitting, setSubmitting] = useState(false);
	const [guardandoAvance, setGuardandoAvance] = useState(false);

	// Borrador local: si ya hay un acta guardada en el servidor (existingValues)
	// esa es la fuente de verdad y no se toca. Si es una carga nueva, se
	// recupera lo que se venía completando ante un corte/cierre accidental.
	const draftKey =
		mesaId && inscripcionId ? `acta-oral-${mesaId}-${inscripcionId}` : null;
	const draftRestauradoRef = useRef<string | null>(null);

	useEffect(() => {
		if (!open) return;
		if (existingValues) {
			setForm({
				...existingValues,
				temasEstudiante: ensureMinRows(existingValues.temasEstudiante),
				temasDocente: ensureMinRows(existingValues.temasDocente),
			});
			return;
		}

		let inicial: OralActFormValues = {
			actaNumero: "",
			folioNumero: "",
			fecha: fechaMesa
				? dayjs(fechaMesa).format("YYYY-MM-DD")
				: dayjs().format("YYYY-MM-DD"),
			curso: curso ?? "",
			notaFinal: defaultNota ?? "",
			observaciones: "",
			temasEstudiante: ensureMinRows([], 3),
			temasDocente: ensureMinRows([], 4),
		};

		if (draftKey && draftRestauradoRef.current !== draftKey) {
			draftRestauradoRef.current = draftKey;
			const draft = loadDraft<OralActFormValues>(draftKey);
			if (draft) {
				inicial = {
					...inicial,
					...draft,
					temasEstudiante: ensureMinRows(draft.temasEstudiante ?? []),
					temasDocente: ensureMinRows(draft.temasDocente ?? []),
				};
			}
		}
		setForm(inicial);

		// El borrador guardado en el servidor (vía "Guardar avance") es más
		// confiable que el local: sobrevive a cambios de PC/navegador, que es
		// justo el caso de un docente yendo y viniendo entre varias mesas.
		// Si existe, pisa lo que se haya recuperado del localStorage.
		if (mesaId && inscripcionId) {
			obtenerBorradorActaOral(mesaId, inscripcionId)
				.then((dto) => {
					setForm((prev) => ({
						...prev,
						actaNumero: dto.acta_numero ?? prev.actaNumero,
						folioNumero: dto.folio_numero ?? prev.folioNumero,
						fecha: dto.fecha ?? prev.fecha,
						curso: dto.curso ?? prev.curso,
						notaFinal: dto.nota_final ?? prev.notaFinal,
						observaciones: dto.observaciones ?? prev.observaciones,
						temasEstudiante: ensureMinRows(
							(dto.temas_estudiante ?? []).map((t) => ({
								id: `${Date.now()}-${Math.random()}`,
								tema: t.tema,
								score: (t.score as OralTopicScore | "") || "",
							})),
							3,
						),
						temasDocente: ensureMinRows(
							(dto.temas_docente ?? []).map((t) => ({
								id: `${Date.now()}-${Math.random()}`,
								tema: t.tema,
								score: (t.score as OralTopicScore | "") || "",
							})),
							4,
						),
					}));
					enqueueSnackbar(
						"Se recuperó un avance guardado de esta acta oral.",
						{ variant: "info" },
					);
				})
				.catch((error) => {
					// 404 = no hay borrador guardado para este estudiante: es el caso
					// normal y no se avisa nada. Un 403/500, en cambio, significa que
					// puede haber un avance que no se pudo recuperar, y callarlo
					// llevaría a recargar todo de cero creyendo que se perdió.
					if (getErrorStatus(error) === 404) return;
					enqueueSnackbar(
						"No se pudo recuperar el avance guardado de esta acta oral.",
						{ variant: "error" },
					);
				});
		}
	}, [open, existingValues, fechaMesa, curso, defaultNota, draftKey, mesaId, inscripcionId]);

	useEffect(() => {
		if (!open || !draftKey || existingValues) return;
		const timer = setTimeout(() => {
			const tieneContenido =
				form.notaFinal.trim() ||
				form.temasEstudiante.some((t) => t.tema.trim()) ||
				form.temasDocente.some((t) => t.tema.trim());
			if (!tieneContenido) return;
			saveDraft(draftKey, form);
		}, 800);
		return () => clearTimeout(timer);
	}, [open, draftKey, existingValues, form]);

	const handleChange = (key: keyof OralActFormValues, value: string) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const updateTopic = (
		section: "temasEstudiante" | "temasDocente",
		id: string,
		patch: Partial<OralActFormTopic>,
	) => {
		setForm((prev) => ({
			...prev,
			[section]: prev[section].map((row) =>
				row.id === id ? { ...row, ...patch } : row,
			),
		}));
	};

	const addTopic = (section: "temasEstudiante" | "temasDocente") => {
		setForm((prev) => ({
			...prev,
			[section]: [...prev[section], createTopicRow()],
		}));
	};

	const removeTopic = (
		section: "temasEstudiante" | "temasDocente",
		id: string,
	) => {
		setForm((prev) => {
			const filtered = prev[section].filter((row) => row.id !== id);
			return {
				...prev,
				[section]: ensureMinRows(
					filtered,
					section === "temasEstudiante" ? 3 : 4,
				),
			};
		});
	};

	const temasEstudiante = useMemo(
		() => ensureMinRows(form.temasEstudiante, 3),
		[form.temasEstudiante],
	);
	const temasDocente = useMemo(
		() => ensureMinRows(form.temasDocente, 4),
		[form.temasDocente],
	);
	const actionDisabled = loading || saving || submitting;

	const handleGenerate = async () => {
		if (submitting) {
			return;
		}
		setSubmitting(true);
		const nextValues: OralActFormValues = {
			...form,
			temasEstudiante,
			temasDocente,
		};
		try {
			await onSave(nextValues);
			if (draftKey) clearDraft(draftKey);
			// El acta oral queda guardada en el sistema para que Secretaría la descargue cuando corresponda.
			onClose();
		} catch {
			// el error ya se notificó fuera
		} finally {
			setSubmitting(false);
		}
	};

	const handleGuardarAvance = async () => {
		if (!mesaId || !inscripcionId || guardandoAvance) return;
		setGuardandoAvance(true);
		try {
			await guardarBorradorActaOral(mesaId, inscripcionId, {
				acta_numero: form.actaNumero || null,
				folio_numero: form.folioNumero || null,
				fecha: form.fecha || null,
				curso: form.curso || null,
				nota_final: form.notaFinal || null,
				observaciones: form.observaciones || null,
				temas_estudiante: temasEstudiante
					.filter((t) => t.tema.trim())
					.map((t) => ({ tema: t.tema, score: t.score || null })),
				temas_docente: temasDocente
					.filter((t) => t.tema.trim())
					.map((t) => ({ tema: t.tema, score: t.score || null })),
			});
			enqueueSnackbar("Avance guardado. Podés continuar más tarde.", {
				variant: "success",
			});
		} catch {
			enqueueSnackbar("No se pudo guardar el avance.", { variant: "error" });
		} finally {
			setGuardandoAvance(false);
		}
	};

	const renderTopicsTable = (
		title: string,
		section: "temasEstudiante" | "temasDocente",
		rows: OralActFormTopic[],
	) => (
		<Box>
			<Stack
				direction="row"
				justifyContent="space-between"
				alignItems="center"
				sx={{ mb: 1 }}
			>
				<Typography variant="subtitle2">{title}</Typography>
				<Button
					size="small"
					startIcon={<AddIcon />}
					onClick={() => addTopic(section)}
				>
					Agregar fila
				</Button>
			</Stack>
			<Table size="small">
				<TableHead>
					<TableRow>
						<TableCell width="55%">Tema / Consigna</TableCell>
						<TableCell width="35%">Puntuación</TableCell>
						<TableCell width="10%" align="center">
							Acciones
						</TableCell>
					</TableRow>
				</TableHead>
				<TableBody>
					{rows.map((row) => (
						<TableRow key={row.id}>
							<TableCell>
								<TextField
									fullWidth
									size="small"
									value={row.tema}
									onChange={(event) =>
										updateTopic(section, row.id, { tema: event.target.value })
									}
								/>
							</TableCell>
							<TableCell>
								<TextField
									select
									fullWidth
									size="small"
									value={row.score}
									onChange={(event) =>
										updateTopic(section, row.id, {
											score: event.target.value as OralTopicScore | "",
										})
									}
								>
									<MenuItem value="">-</MenuItem>
									{scoreOptions.map((option) => (
										<MenuItem key={option.value} value={option.value}>
											{option.label}
										</MenuItem>
									))}
								</TextField>
							</TableCell>
							<TableCell align="center">
								<IconButton
									size="small"
									onClick={() => removeTopic(section, row.id)}
								>
									<DeleteIcon fontSize="small" />
								</IconButton>
							</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
		</Box>
	);

	return (
		<Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
			<DialogTitle>Acta de examen oral · {estudianteNombre}</DialogTitle>
			<DialogContent dividers>
				{loading ? (
					<Stack alignItems="center" justifyContent="center" py={6}>
						<CircularProgress />
					</Stack>
				) : (
					<Stack spacing={2}>
						<Grid container spacing={2}>
							<Grid item xs={12} md={4}>
								<TextField
									label="Acta N°"
									fullWidth
									size="small"
									value={form.actaNumero}
									onChange={(event) =>
										handleChange("actaNumero", event.target.value)
									}
								/>
							</Grid>
							<Grid item xs={12} md={4}>
								<TextField
									label="Folio N°"
									fullWidth
									size="small"
									value={form.folioNumero}
									onChange={(event) =>
										handleChange("folioNumero", event.target.value)
									}
								/>
							</Grid>
							<Grid item xs={12} md={4}>
								<TextField
									label="Fecha"
									type="date"
									fullWidth
									size="small"
									InputLabelProps={{ shrink: true }}
									value={form.fecha}
									onChange={(event) =>
										handleChange("fecha", event.target.value)
									}
								/>
							</Grid>
							<Grid item xs={12} md={6}>
								<TextField
									label="Curso / Comisión"
									fullWidth
									size="small"
									value={form.curso}
									onChange={(event) =>
										handleChange("curso", event.target.value)
									}
								/>
							</Grid>
							<Grid item xs={12} md={6}>
								<TextField
									select
									label="Nota final"
									fullWidth
									size="small"
									value={form.notaFinal}
									onChange={(event) =>
										handleChange("notaFinal", event.target.value)
									}
								>
									<MenuItem value="">-</MenuItem>
									{NOTA_FINAL_OPTIONS.map((n) => (
										<MenuItem key={n} value={n}>
											{n}
										</MenuItem>
									))}
								</TextField>
							</Grid>
						</Grid>

						<Divider />

						{renderTopicsTable(
							"Temas elegidos por el estudiante",
							"temasEstudiante",
							temasEstudiante,
						)}
						{renderTopicsTable(
							"Temas sugeridos por el docente",
							"temasDocente",
							temasDocente,
						)}

						<TextField
							label="Observaciones"
							multiline
							minRows={3}
							fullWidth
							value={form.observaciones}
							onChange={(event) =>
								handleChange("observaciones", event.target.value)
							}
						/>
					</Stack>
				)}
			</DialogContent>
			<DialogActions>
				<Button onClick={onClose}>Cerrar</Button>
				{mesaId && inscripcionId && !existingValues && (
					<Button
						variant="outlined"
						onClick={handleGuardarAvance}
						disabled={actionDisabled || guardandoAvance}
						startIcon={
							guardandoAvance ? (
								<CircularProgress size={16} />
							) : undefined
						}
					>
						{guardandoAvance ? "Guardando..." : "Guardar avance"}
					</Button>
				)}
				<Button
					variant="contained"
					onClick={handleGenerate}
					disabled={actionDisabled}
					startIcon={
						actionDisabled ? (
							<CircularProgress size={16} color="inherit" />
						) : undefined
					}
				>
					{actionDisabled ? "Generando..." : "Generar acta oral"}
				</Button>
			</DialogActions>
		</Dialog>
	);
};

export default OralExamActaDialog;
