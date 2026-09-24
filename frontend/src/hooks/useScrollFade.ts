import { useState, useEffect, useRef, useCallback } from "react";

export interface UseScrollFadeReturn<T extends HTMLElement = HTMLDivElement> {
	scrollRef: React.RefObject<T | null>;
	canScrollLeft: boolean;
	canScrollRight: boolean;
	checkScroll: () => void;
	setTargetElement: (element: HTMLElement | null) => void;
}

/**
 * Hook to detect whether a container can be scrolled horizontally to the left or right,
 * allowing visual affordances (such as gradient fades or arrows) to be displayed dynamically.
 */
export function useScrollFade<T extends HTMLElement = HTMLDivElement>(
	tolerance = 2
): UseScrollFadeReturn<T> {
	const scrollRef = useRef<T | null>(null);
	const [targetEl, setTargetElement] = useState<HTMLElement | null>(null);
	const [canScrollLeft, setCanScrollLeft] = useState(false);
	const [canScrollRight, setCanScrollRight] = useState(false);

	const checkScroll = useCallback(() => {
		const el = targetEl || scrollRef.current;
		if (!el) {
			setCanScrollLeft(false);
			setCanScrollRight(false);
			return;
		}

		const { scrollLeft, scrollWidth, clientWidth } = el;
		const maxScroll = scrollWidth - clientWidth;

		setCanScrollLeft(scrollLeft > tolerance);
		setCanScrollRight(maxScroll > tolerance && scrollLeft < maxScroll - tolerance);
	}, [targetEl, tolerance]);

	useEffect(() => {
		const el = targetEl || scrollRef.current;
		if (!el) return;

		checkScroll();

		el.addEventListener("scroll", checkScroll, { passive: true });

		let resizeObserver: ResizeObserver | null = null;
		if (typeof ResizeObserver !== "undefined") {
			resizeObserver = new ResizeObserver(() => {
				checkScroll();
			});
			resizeObserver.observe(el);
			// Also observe children if possible for content expansion
			if (el.firstElementChild) {
				resizeObserver.observe(el.firstElementChild);
			}
		}

		const handleResize = () => checkScroll();
		window.addEventListener("resize", handleResize);

		return () => {
			el.removeEventListener("scroll", checkScroll);
			window.removeEventListener("resize", handleResize);
			if (resizeObserver) {
				resizeObserver.disconnect();
			}
		};
	}, [targetEl, checkScroll]);

	return {
		scrollRef,
		canScrollLeft,
		canScrollRight,
		checkScroll,
		setTargetElement,
	};
}
