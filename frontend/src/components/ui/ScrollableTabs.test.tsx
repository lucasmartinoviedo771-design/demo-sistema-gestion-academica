import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import Tab from "@mui/material/Tab";
import { afterEach, describe, expect, it, vi } from "vitest";
import React, { useState } from "react";
import ScrollableTabs from "./ScrollableTabs";
import ScrollFadeContainer from "./ScrollFadeContainer";

afterEach(() => {
	cleanup();
});

describe("ScrollableTabs", () => {
	const TestComponent = () => {
		const [tab, setTab] = useState(0);
		return (
			<ScrollableTabs value={tab} onChange={(_, val) => setTab(val)}>
				<Tab label="Pestaña 1" />
				<Tab label="Pestaña 2" />
				<Tab label="Pestaña 3" />
			</ScrollableTabs>
		);
	};

	it("renderiza todas las pestañas correctamente", () => {
		render(<TestComponent />);
		expect(screen.getByText("Pestaña 1")).toBeInTheDocument();
		expect(screen.getByText("Pestaña 2")).toBeInTheDocument();
		expect(screen.getByText("Pestaña 3")).toBeInTheDocument();
	});

	it("permite cambiar de pestaña al hacer click", () => {
		render(<TestComponent />);
		const tab2 = screen.getByText("Pestaña 2");
		fireEvent.click(tab2);
		expect(tab2.closest("button")).toHaveAttribute("aria-selected", "true");
	});

	it("aplica scrollable y botones automáticos por defecto", () => {
		const { container } = render(<TestComponent />);
		const tabsRoot = container.querySelector(".MuiTabs-root");
		expect(tabsRoot).toBeInTheDocument();
		expect(container.querySelector(".MuiTabs-scroller")).toBeInTheDocument();
	});
});

describe("ScrollFadeContainer", () => {
	it("renderiza el contenido hijo dentro del contenedor", () => {
		render(
			<ScrollFadeContainer>
				<div data-testid="child-content">Contenido de prueba</div>
			</ScrollFadeContainer>
		);
		expect(screen.getByTestId("child-content")).toBeInTheDocument();
		expect(screen.getByText("Contenido de prueba")).toBeInTheDocument();
	});
});
