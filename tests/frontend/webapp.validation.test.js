import fs from "node:fs";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

const APP_JS_PATH = path.resolve(process.cwd(), "webapp/app.js");

function nextWeekdayAtLocalTime(targetWeekday, hour, minute) {
  const date = new Date();
  date.setSeconds(0, 0);

  const dayDiff = (targetWeekday - date.getDay() + 7) % 7;
  date.setDate(date.getDate() + (dayDiff === 0 ? 7 : dayDiff));
  date.setHours(hour, minute, 0, 0);
  return date;
}

function setupDom() {
  document.body.innerHTML = `
    <div id="category-tabs"></div>
    <div id="catalog"></div>
    <section id="order-form-section">
      <form id="order-form">
        <input id="client-name" type="text" />
        <input id="phone-number" type="tel" />
        <input id="pickup-datetime" type="datetime-local" />
        <div id="pickup-custom-error" class="d-none"></div>
        <input id="allergen-confirmation" type="checkbox" />
      </form>
    </section>
    <div id="total-amount"></div>
    <button id="confirm-order-btn" type="button"></button>
    <button id="scroll-top-btn" type="button"></button>
    <div id="modal-product-content"></div>
    <div id="productModal"></div>
  `;
}

function loadAppScript({ startParam } = {}) {
  window.Telegram = {
    WebApp: {
      expand: () => {},
      sendData: () => {},
      close: () => {},
      initDataUnsafe: startParam ? { start_param: startParam } : {},
    },
  };

  window.bootstrap = {
    Modal: {
      getInstance: () => null,
    },
  };

  const scriptContent = fs.readFileSync(APP_JS_PATH, "utf8");
  window.eval(scriptContent);
}

describe("WebApp pickup date validation", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    localStorage.clear();
    setupDom();
  });

  it("sets max datetime to today + 60 days", () => {
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const expectedMax = window.toDatetimeLocalValue(window.getMaxAllowedPickupDate());

    expect(pickupInput.max).toBe(expectedMax);
  });

  it("shows bakery phone error when selected date is more than 60 days ahead", () => {
    window.history.replaceState(
      {},
      "",
      "/?bakery_phone=%2B33%201%2023%2045%2067%2089"
    );
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const customError = document.getElementById("pickup-custom-error");

    const tooFarDate = new Date();
    tooFarDate.setDate(tooFarDate.getDate() + 61);
    tooFarDate.setHours(10, 0, 0, 0);

    pickupInput.value = window.toDatetimeLocalValue(tooFarDate);
    window.validateForm();

    expect(customError.classList.contains("d-none")).toBe(false);
    expect(customError.textContent).toContain("au-delà de 60 jours");
    expect(customError.textContent).toContain("+33 1 23 45 67 89");
  });

  it("uses phone from Telegram start_param when URL phone is missing", () => {
    loadAppScript({ startParam: "campaign=promo;phone=%2B33988776655" });

    const pickupInput = document.getElementById("pickup-datetime");
    const customError = document.getElementById("pickup-custom-error");

    const tooFarDate = new Date();
    tooFarDate.setDate(tooFarDate.getDate() + 61);
    tooFarDate.setHours(10, 0, 0, 0);

    pickupInput.value = window.toDatetimeLocalValue(tooFarDate);
    window.validateForm();

    expect(customError.textContent).toContain("+33988776655");
  });

  it("shows working hours error for Sunday after 13:00", () => {
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const customError = document.getElementById("pickup-custom-error");

    const sundayAfternoon = nextWeekdayAtLocalTime(0, 14, 0);
    pickupInput.value = window.toDatetimeLocalValue(sundayAfternoon);
    window.validateForm();

    expect(customError.classList.contains("d-none")).toBe(false);
    expect(customError.textContent).toContain("Nos horaires de retrait sont");
  });

  it("shows min lead-time error for a pickup earlier than 30 minutes", () => {
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const customError = document.getElementById("pickup-custom-error");

    const tooSoonDate = new Date(Date.now() + 10 * 60 * 1000);
    tooSoonDate.setMinutes(Math.ceil(tooSoonDate.getMinutes() / 15) * 15);
    tooSoonDate.setSeconds(0, 0);

    pickupInput.value = window.toDatetimeLocalValue(tooSoonDate);
    window.validateForm();

    expect(customError.classList.contains("d-none")).toBe(false);
    expect(customError.textContent).toContain("au moins 30 minutes");
  });

  it("rounds time to nearest 15-minute slot on picker change", () => {
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const nextMonday = nextWeekdayAtLocalTime(1, 10, 7);
    pickupInput.value = window.toDatetimeLocalValue(nextMonday);

    pickupInput.dispatchEvent(new Event("change", { bubbles: true }));

    const roundedDate = new Date(pickupInput.value);
    expect(roundedDate.getMinutes() % 15).toBe(0);
  });

  it("clears custom pickup error for a valid date in working hours", () => {
    loadAppScript();

    const pickupInput = document.getElementById("pickup-datetime");
    const customError = document.getElementById("pickup-custom-error");

    const mondayMorning = nextWeekdayAtLocalTime(1, 10, 30);
    pickupInput.value = window.toDatetimeLocalValue(mondayMorning);
    window.validateForm();

    expect(customError.classList.contains("d-none")).toBe(true);
    expect(customError.textContent).toBe("");
  });
});
