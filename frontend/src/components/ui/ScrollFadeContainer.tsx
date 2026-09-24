import React, { useRef, useEffect } from "react";
import Box, { BoxProps } from "@mui/material/Box";
import { useScrollFade } from "@/hooks/useScrollFade";

export interface ScrollFadeContainerProps extends BoxProps {
	/**
	 * Color base para los degradados laterales de desborde.
	 * Por defecto toma `theme.palette.background.paper`.
	 */
	fadeColor?: string;
	/**
	 * Si es true, desactiva los degradados visuales de desborde.
	 */
	disableFade?: boolean;
	/**
	 * Ancho en px del degradado. Por defecto 28.
	 */
	fadeWidth?: number;
}

/**
 * Contenedor con affordance visual que renderiza gradientes dinámicos en los bordes
 * cuando el contenido horizontalmente scrolleable desborda hacia la izquierda o derecha.
 */
export const ScrollFadeContainer: React.FC<ScrollFadeContainerProps> = ({
	fadeColor,
	disableFade = false,
	fadeWidth = 28,
	children,
	sx,
	...props
}) => {
	const rootRef = useRef<HTMLDivElement | null>(null);
	const { canScrollLeft, canScrollRight, setTargetElement } = useScrollFade();

	useEffect(() => {
		if (!rootRef.current) return;
		// Si el root mismo no es el elemento con overflow, buscamos el primer elemento hijo scrolleable
		let target: HTMLElement = rootRef.current;
		const computed = window.getComputedStyle(rootRef.current);
		if (computed.overflowX !== "auto" && computed.overflowX !== "scroll") {
			const scrollableChild = rootRef.current.querySelector<HTMLElement>(
				".MuiTableContainer-root, [data-scrollable='true']"
			);
			if (scrollableChild) {
				target = scrollableChild;
			}
		}
		setTargetElement(target);
	}, [setTargetElement]);

	return (
		<Box
			ref={rootRef}
			sx={{
				position: "relative",
				width: "100%",
				...(Array.isArray(sx) ? sx : [sx]),
			}}
			{...props}
		>
			{!disableFade && (
				<Box
					sx={{
						position: "absolute",
						left: 0,
						top: 0,
						bottom: 0,
						width: fadeWidth,
						pointerEvents: "none",
						zIndex: 2,
						background:
							fadeColor ?? "linear-gradient(to right, rgba(0,0,0,0.16), rgba(0,0,0,0))",
						boxShadow: "inset 10px 0 8px -8px rgba(0,0,0,0.25)",
						opacity: canScrollLeft ? 1 : 0,
						transition: "opacity 0.25s ease-in-out",
					}}
				/>
			)}

			{children}

			{!disableFade && (
				<Box
					sx={{
						position: "absolute",
						right: 0,
						top: 0,
						bottom: 0,
						width: fadeWidth,
						pointerEvents: "none",
						zIndex: 2,
						background:
							fadeColor ?? "linear-gradient(to left, rgba(0,0,0,0.16), rgba(0,0,0,0))",
						boxShadow: "inset -10px 0 8px -8px rgba(0,0,0,0.25)",
						opacity: canScrollRight ? 1 : 0,
						transition: "opacity 0.25s ease-in-out",
					}}
				/>
			)}
		</Box>
	);
};

export default ScrollFadeContainer;
