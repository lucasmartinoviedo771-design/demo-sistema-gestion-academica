import type { ReactNode } from "react";
import { Navigate, Route } from "react-router-dom";
import { PublicOnlyRoute } from "@/router/guards";
import { lazyPage } from "@/utils/lazy";

type PublicRoutesProps = {
	preinscripcionElement: ReactNode;
};

const LoginPage = lazyPage(() => import("../../pages/LoginPage"));
const AuthCallbackPage = lazyPage(
	() => import("../../pages/Auth/CallbackPage"),
);
const RoleSelectorPage = lazyPage(
	() => import("../../pages/Auth/RoleSelectorPage"),
);
const DocenteAsistenciaPage = lazyPage(
	() => import("../../pages/Docentes/DocenteAsistenciaPage"),
);
const InscripcionPreview = lazyPage(
	() => import("../../pages/InscripcionPreview"),
);
const Forbidden = lazyPage(() => import("../../pages/Forbidden"));
const ForgotPasswordPage = lazyPage(
	() => import("../../pages/Auth/ForgotPasswordPage"),
);
const ResetPasswordPage = lazyPage(
	() => import("../../pages/Auth/ResetPasswordPage"),
);

export const buildPublicRoutes = ({
	preinscripcionElement,
}: PublicRoutesProps) => (
	<>
		<Route index element={<Navigate to="/preinscripcion" replace />} />
		<Route path="/preinscripcion" element={preinscripcionElement} />
		<Route path="/debug/inscripcion-preview" element={<InscripcionPreview />} />
		<Route
			path="/login"
			element={
				<PublicOnlyRoute>
					<LoginPage />
				</PublicOnlyRoute>
			}
		/>
		{/*
			Sin PublicOnlyRoute (igual que /reset-password más abajo): pedir un
			link nuevo no debería depender de si hay sesión activa en el
			navegador — si no, el link "pedí uno nuevo" que se muestra en el
			propio /reset-password cuando el token venció redirige al usuario
			a su sesión en vez de dejarlo pedir el link.
		*/}
		<Route path="/olvide-password" element={<ForgotPasswordPage />} />
		{/*
			Sin PublicOnlyRoute a propósito: el reset de contraseña se valida
			exclusivamente por el token de la URL contra el backend
			(password-reset/confirm), nunca por sesión de cookies. Si hubiera
			cualquier sesión activa en el navegador (propia o de otro usuario
			en una PC compartida), PublicOnlyRoute redirigía antes de mostrar
			el formulario, ignorando si el token era válido o estaba vencido.
		*/}
		<Route path="/reset-password" element={<ResetPasswordPage />} />
		<Route path="/seleccionar-rol" element={<RoleSelectorPage />} />
		<Route path="/auth/callback" element={<AuthCallbackPage />} />
		<Route path="/docentes/asistencia" element={<DocenteAsistenciaPage />} />
		<Route path="/403" element={<Forbidden />} />
	</>
);
