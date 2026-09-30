import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";

// Medicine name field with autocomplete (FR-01). Brand, generic or misspelled names all accepted;
// the backend normalises them.
export default function DrugInput({ label, value, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(-1);
  const id = useId();
  const timer = useRef();

  useEffect(() => {
    clearTimeout(timer.current);
    if (!value.trim()) return setItems([]);
    timer.current = setTimeout(() => {
      api.suggest(value).then(setItems).catch(() => setItems([]));
    }, 150);
    return () => clearTimeout(timer.current);
  }, [value]);

  const shown = open && items.length > 0 && !(items.length === 1 && items[0] === value.toLowerCase());

  function pick(name) {
    onChange(name);
    setOpen(false);
    setActive(-1);
  }

  function onKeyDown(e) {
    if (!shown) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % items.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a <= 0 ? items.length - 1 : a - 1)); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); pick(items[active]); }
    else if (e.key === "Escape") setOpen(false);
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="block text-sm font-bold text-muted mb-1">{label}</label>
      <input
        id={id}
        role="combobox"
        aria-expanded={shown}
        aria-controls={`${id}-list`}
        aria-activedescendant={active >= 0 ? `${id}-${active}` : undefined}
        autoComplete="off"
        spellCheck="false"
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        className="w-full h-12 px-3 text-lg bg-surface border-2 border-rule rounded-md placeholder:text-muted/60 focus:border-act focus:outline-none"
      />
      {shown && (
        <ul id={`${id}-list`} role="listbox"
            className="absolute z-20 left-0 right-0 mt-1 bg-surface border-2 border-rule rounded-md shadow-lg overflow-hidden">
          {items.map((name, i) => (
            <li key={name} id={`${id}-${i}`} role="option" aria-selected={i === active}
                onMouseDown={(e) => { e.preventDefault(); pick(name); }}
                className={`px-3 py-2 cursor-pointer text-base ${i === active ? "bg-act text-white" : "hover:bg-blister"}`}>
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
