// tablesort.js

// Utility functions
const createEvent = (name) => {
  let evt;
  if (!window.CustomEvent || typeof window.CustomEvent !== "function") {
    evt = document.createEvent("CustomEvent");
    evt.initCustomEvent(name, false, false, undefined);
  } else {
    evt = new CustomEvent(name);
  }
  return evt;
};

const getInnerText = (el, options) => {
  return (
    el.getAttribute(options.sortAttribute || "data-sort") ||
    el.textContent ||
    el.innerText ||
    ""
  );
};

const caseInsensitiveSort = (a, b) => {
  a = a.trim().toLowerCase();
  b = b.trim().toLowerCase();
  if (a === b) return 0;
  return a < b ? 1 : -1;
};

const getCellByKey = (cells, key) => {
  return Array.from(cells).find((cell) =>
    cell.getAttribute("data-sort-column-key") === key
  );
};

const stabilize = (sort, antiStabilize) => (a, b) => {
  const unstableResult = sort(a.td, b.td);
  if (unstableResult === 0) {
    return antiStabilize ? b.index - a.index : a.index - b.index;
  }
  return unstableResult;
};

const sortOptions = [];

class Tablesort {
  constructor(el, options = {}) {
    if (!(el instanceof HTMLTableElement)) {
      throw new Error("Element must be a table");
    }
    this.init(el, options);
  }

  static extend(name, pattern, sort) {
    if (typeof pattern !== "function" || typeof sort !== "function") {
      throw new Error("Pattern and sort must be a function");
    }
    sortOptions.push({ name, pattern, sort });
  }

  init(el, options) {
    this.table = el;
    this.thead = false;
    this.options = options;

    let firstRow;
    if (el.tHead && el.tHead.rows.length > 0) {
      firstRow = Array.from(el.tHead.rows).find(
        (row) => row.getAttribute("data-sort-method") === "thead"
      ) || el.tHead.rows[el.tHead.rows.length - 1];
      this.thead = true;
    } else {
      firstRow = el.rows[0];
    }

    if (!firstRow) return;

    const onClick = (event) => {
      if (this.current && this.current !== event.currentTarget) {
        this.current.removeAttribute("aria-sort");
      }
      this.current = event.currentTarget;
      this.sortTable(event.currentTarget);
    };

    for (const cell of firstRow.cells) {
      cell.setAttribute("role", "columnheader");
      if (cell.getAttribute("data-sort-method") !== "none") {
        cell.tabIndex = 0;
        cell.addEventListener("click", onClick, false);
        if (cell.getAttribute("data-sort-default") !== null) {
          this.current = cell;
          this.sortTable(cell);
        }
      }
    }
  }

  sortTable(header, update = false) {
    const columnKey = header.getAttribute("data-sort-column-key");
    const column = header.cellIndex;
    let sortFunction = caseInsensitiveSort;
    let items = [];
    let i = this.thead ? 0 : 1;
    const sortMethod = header.getAttribute("data-sort-method");
    let sortOrder = header.getAttribute("aria-sort");

    this.table.dispatchEvent(createEvent("beforeSort"));

    if (!update) {
      sortOrder =
        sortOrder === "ascending"
          ? "descending"
          : sortOrder === "descending"
          ? "ascending"
          : this.options.descending
          ? "descending"
          : "ascending";

      header.setAttribute("aria-sort", sortOrder);
    }

    if (this.table.rows.length < 2) return;

    while (items.length < 3 && i < this.table.tBodies[0].rows.length) {
      const cell = columnKey
        ? getCellByKey(this.table.tBodies[0].rows[i].cells, columnKey)
        : this.table.tBodies[0].rows[i].cells[column];
      const item = cell ? getInnerText(cell, this.options).trim() : "";
      if (item.length > 0) items.push(item);
      i++;
    }

    for (const option of sortOptions) {
      if (sortMethod && option.name === sortMethod) {
        sortFunction = option.sort;
        break;
      } else if (items.every(option.pattern)) {
        sortFunction = option.sort;
        break;
      }
    }

    this.col = column;
    for (const tbody of this.table.tBodies) {
      const newRows = [];
      const noSorts = {};
      let totalRows = 0;
      let noSortsSoFar = 0;

      for (const row of tbody.rows) {
        if (row.getAttribute("data-sort-method") === "none") {
          noSorts[totalRows] = row;
        } else {
          const cell = columnKey
            ? getCellByKey(row.cells, columnKey)
            : row.cells[this.col];
          newRows.push({
            tr: row,
            td: cell ? getInnerText(cell, this.options) : "",
            index: totalRows,
          });
        }
        totalRows++;
      }

      if (sortOrder === "descending") {
        newRows.sort(stabilize(sortFunction, true));
      } else {
        newRows.sort(stabilize(sortFunction, false)).reverse();
      }

      for (let j = 0; j < totalRows; j++) {
        const row = noSorts[j] || newRows[j - noSortsSoFar].tr;
        tbody.appendChild(row);
      }
    }

    this.table.dispatchEvent(createEvent("afterSort"));
  }

  refresh() {
    if (this.current) {
      this.sortTable(this.current, true);
    }
  }
}

// Number sorting extension
const cleanNumber = (i) => i.replace(/[^\-?0-9.]/g, "");
const compareNumber = (a, b) => (parseFloat(b) || 0) - (parseFloat(a) || 0);

Tablesort.extend(
  "number",
  (item) =>
    item.match(/^[-+]?[£\x24Û¢´€]?\d+\s*([,\.]\d{0,2})/) ||
    item.match(/^[-+]?\d+\s*([,\.]\d{0,2})?[£\x24Û¢´€]/) ||
    item.match(/^[-+]?(\d)*-?([,\.]){0,1}-?(\d)+([E,e][\-+][\d]+)?%?$/),
  (a, b) => compareNumber(cleanNumber(a), cleanNumber(b))
);

export default Tablesort;
