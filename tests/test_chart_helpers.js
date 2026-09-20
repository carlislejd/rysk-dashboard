/* Run with: node tests/test_chart_helpers.js
   This stays dependency-free so the shared browser helper can be checked in CI
   environments that only provide Node. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const listeners = {};
const chart = {
  dataset: {},
  attributes: {},
  classList: {
    values: new Set(),
    add(value) { this.values.add(value); },
    remove(value) { this.values.delete(value); },
    contains(value) { return this.values.has(value); },
  },
  getAttribute(key) { return this.attributes[key]; },
  setAttribute(key, value) { this.attributes[key] = value; },
  removeAttribute(key) { delete this.attributes[key]; },
  addEventListener() {},
  removeEventListener() {},
  isConnected: true,
  textContent: "",
};
const document = {
  documentElement: {
    attributes: {},
    getAttribute(key) { return this.attributes[key]; },
    setAttribute(key, value) { this.attributes[key] = value; },
  },
  getElementById() { return chart; },
  querySelectorAll(selector) { return selector === ".rysk-chart" ? [chart] : []; },
  addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  dispatchEvent(event) { (listeners[event.type] || []).forEach((handler) => handler(event)); },
};
let renderCount = 0;
let received;
const context = {
  window: {},
  document,
  localStorage: { getItem: () => "light", setItem() {} },
  Plotly: {
    react(element, traces) { renderCount += 1; received = traces; element.data = traces; },
    purge(element) { delete element.data; },
    Plots: { resize() {} },
  },
  ResizeObserver: class { observe() {} },
  requestAnimationFrame: (handler) => handler(),
  cancelAnimationFrame() {},
  CustomEvent: class { constructor(type) { this.type = type; } },
};

vm.createContext(context);
vm.runInContext(fs.readFileSync("static/js/utils.js", "utf8"), context);
vm.runInContext(
  "window.RyskCharts.render('chart', [{ x: [new Date('2026-01-01T00:00:00Z')], marker: { color: window.RyskCharts.colors().forest } }], {});",
  context,
);
assert.equal(Object.prototype.toString.call(received[0].x[0]), "[object Date]");
assert.equal(received[0].x[0].toISOString(), "2026-01-01T00:00:00.000Z");

document.documentElement.setAttribute("data-theme", "dark");
document.dispatchEvent(new context.CustomEvent("rysk:themechange"));
assert.equal(received[0].marker.color, "#a7dbb7");

context.window.RyskCharts.empty("chart", "No records");
const countAfterEmpty = renderCount;
document.dispatchEvent(new context.CustomEvent("rysk:themechange"));
assert.equal(renderCount, countAfterEmpty, "empty charts must not revive during a theme change");
assert.equal(chart.textContent, "No records");

context.window.RyskCharts.render("chart", [], {});
assert.equal(chart.textContent, "", "render restores a chart after an empty state");
assert.equal(chart.attributes.role, "img");

console.log("chart helper tests passed");
