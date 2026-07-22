import { useEffect, useId, useRef, useState } from "react";
import type { CurrentActor } from "../api/client";

type AccountMenuVariant = "admin" | "sales";

export default function AccountMenu({
  actor,
  onRequestLogout,
  roleLabel,
  variant,
}: {
  actor: CurrentActor;
  onRequestLogout: () => void;
  roleLabel: string;
  variant: AccountMenuVariant;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const isSales = variant === "sales";

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function closeWhenClickingOutside(event: PointerEvent) {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    }

    function closeWithEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      event.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", closeWhenClickingOutside);
    window.addEventListener("keydown", closeWithEscape);
    return () => {
      document.removeEventListener("pointerdown", closeWhenClickingOutside);
      window.removeEventListener("keydown", closeWithEscape);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className={`account-menu account-menu-${variant}`}>
      <button
        ref={triggerRef}
        className={`account-menu-trigger ${
          isSales ? "sales-user-chip sales-account-menu-trigger" : "admin-user-pill admin-account-menu-trigger"
        }`}
        type="button"
        aria-controls={menuId}
        aria-expanded={isOpen}
        aria-label={`${isOpen ? "关闭" : "打开"}${actor.name}的账户菜单`}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className={isSales ? "sales-avatar sales-avatar-small" : "admin-avatar admin-avatar-small"}>
          {actor.name.slice(0, 1).toUpperCase()}
        </span>
        <span className={isSales ? "hidden sm:block" : "min-w-0 truncate"}>{actor.name}</span>
        {isSales && <span className="hidden xl:block">{roleLabel}</span>}
        <svg
          className="account-menu-chevron"
          aria-hidden="true"
          fill="none"
          viewBox="0 0 16 16"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.8"
        >
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>

      {isOpen && (
        <section id={menuId} className="account-menu-popover" aria-label="账户操作">
          <div className="account-menu-summary">
            <span className="account-menu-summary-avatar">
              {actor.name.slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate">{actor.name}</p>
              <span>{roleLabel}</span>
            </div>
          </div>
          <div className="account-menu-divider" />
          <button
            className="btn-danger account-menu-logout"
            type="button"
            onClick={() => {
              setIsOpen(false);
              onRequestLogout();
            }}
          >
            <svg
              aria-hidden="true"
              fill="none"
              viewBox="0 0 20 20"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.7"
            >
              <path d="M8 4H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3" />
              <path d="m12 7 3 3-3 3M6 10h9" />
            </svg>
            退出登录
          </button>
        </section>
      )}
    </div>
  );
}
