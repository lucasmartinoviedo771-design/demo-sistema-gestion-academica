import React, { useRef, useEffect, forwardRef } from "react";
import Tabs, { TabsProps } from "@mui/material/Tabs";
import Box from "@mui/material/Box";
import { SxProps, Theme } from "@mui/material/styles";
import { useScrollFade } from "@/hooks/useScrollFade";

export interface ScrollableTabsProps extends TabsProps {
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
	 * Estilos adicionales para el contenedor wrapper del componente.
	 */
	wrapperSx?: SxProps<Theme>;
}

export const ScrollableTabs = forwardRef<HTMLDivElement, ScrollableTabsProps>(
	function ScrollableTabs(
		{
			fadeColor,
			disableFade = false,
			wrapperSx,
			variant = "scrollable",
			scrollButtons = "auto",
			allowScrollButtonsMobile = true,
			children,
			value,
			sx,
			...props
		},
		ref
	) {
		const rootRef = useRef<HTMLDivElement | null>(null);
		const { canScrollLeft, canScrollRight, checkScroll, setTargetElement } =
			useScrollFade();

		useEffect(() => {
			if (!rootRef.current) return;
			// El elemento scrolleable real de MUI Tabs es la clase .MuiTabs-scroller
			const scroller = rootRef.current.querySelector<HTMLElement>(".MuiTabs-scroller");
			if (scroller) {
				setTargetElement(scroller);
			}
		}, [setTargetElement]);

		// Re-verificar scroll cuando cambia la pestaña activa o los children
		useEffect(() => {
			const timer = setTimeout(() => {
				checkScroll();
			}, 150);
			return () => clearTimeout(timer);
		}, [value, children, checkScroll]);

		const isScrollable = variant === "scrollable";
		const showFade = !disableFade && isScrollable;

		return (
			<Box
				ref={rootRef}
				sx={{
					position: "relative",
					width: "100%",
					...wrapperSx,
				}}
			>
				{showFade && (
					<Box
						sx={{
							position: "absolute",
							left: 0,
							top: 0,
							bottom: 0,
							width: 28,
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

				<Tabs
					ref={ref}
					variant={variant}
					scrollButtons={scrollButtons}
					allowScrollButtonsMobile={allowScrollButtonsMobile}
					value={value}
					sx={[
						{
							"& .MuiTabs-scroller": {
								WebkitOverflowScrolling: "touch",
							},
						},
						...(Array.isArray(sx) ? sx : [sx]),
					]}
					{...props}
				>
					{children}
				</Tabs>

				{showFade && (
					<Box
						sx={{
							position: "absolute",
							right: 0,
							top: 0,
							bottom: 0,
							width: 28,
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
	}
);

export default ScrollableTabs;
