const tg = window.Telegram.WebApp;
tg.expand();

const catalogStructure = {
	Pains: [
		"Pains traditionnels",
		"Pains saveurs",
		"Pains équilibre & BIO",
		"Baguettes",
		"Pains burgers & mini pains",
	],
	"Pâtisseries": [
		"Pâtisseries individuelles",
		"Entremets à partager",
		"Tartes & flans à partager",
	],
	Viennoiseries: [
		"Les incontournables",
		"Nos spécialités",
		"Nos brioches",
		"Mini viennoiseries & chouquettes",
		"Nos gourmandises",
	],
};

const productNameSeeds = [
	"Tradition",
	"Maison",
	"Signature",
	"Gourmand",
	"Doré",
	"Artisanal",
];

function getPriceForIndex(index) {
	const prices = [1.2, 1.8, 2.4, 3.6, 5.5, 7.9, 9.8, 12.0];
	return prices[index % prices.length];
}

function buildProductsFromStructure(structure) {
	const generatedProducts = [];
	let idCounter = 1;

	Object.entries(structure).forEach(([category, subcategories]) => {
		subcategories.forEach((subcategory) => {
			for (let index = 1; index <= 6; index += 1) {
				const nameSeed = productNameSeeds[(index - 1) % productNameSeeds.length];
				generatedProducts.push({
					id: idCounter,
					name: `${nameSeed} ${subcategory} ${index}`,
					category,
					subcategory,
					price: getPriceForIndex(idCounter),
					image: "https://placehold.co/300x300/fbf9f6/151515?text=La+Talemelerie",
				});
				idCounter += 1;
			}
		});
	});

	return generatedProducts;
}

const products = buildProductsFromStructure(catalogStructure);
const cart = {};
let currentCategory = "Pains";

const categoryTabsElement = document.getElementById("category-tabs");
const catalogElement = document.getElementById("catalog");
const checkoutForm = document.getElementById("order-form") || document.getElementById("checkout-form");
const orderFormSection = document.getElementById("order-form-section") || checkoutForm;
const clientNameInput = document.getElementById("client-name");
const phoneNumberInput = document.getElementById("phone-number");
const pickupDatetimeInput = document.getElementById("pickup-datetime");
const allergenCheckbox = document.getElementById("allergen-confirmation");
const totalAmountElement = document.getElementById("total-amount");
const confirmOrderButton = document.getElementById("confirm-order-btn");

// FIX: Local timezone calculation and 15-minute step rounding
function initializePickupTime() {
	if (!pickupDatetimeInput) return;

	const minDate = new Date();
	minDate.setMinutes(minDate.getMinutes() + 30); // Base +30 mins rule

	// Round up to the nearest 15-minute interval
	minDate.setMinutes(Math.ceil(minDate.getMinutes() / 15) * 15);
	minDate.setSeconds(0, 0); // Zero out seconds

	// Correct timezone offset for HTML datetime-local (avoid UTC mismatch)
	const offset = minDate.getTimezoneOffset() * 60000;
	const localMinDate = new Date(minDate.getTime() - offset);
	
	pickupDatetimeInput.min = localMinDate.toISOString().slice(0, 16);
}
initializePickupTime();

function formatPrice(amount) {
	return new Intl.NumberFormat("fr-FR", {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(amount);
}

function getProductById(productId) {
	return products.find((product) => product.id === productId);
}

function getCartQuantity(productId) {
	return cart[productId] || 0;
}

function getCartItems() {
	return products
		.filter((product) => getCartQuantity(product.id) > 0)
		.map((product) => {
			const quantity = getCartQuantity(product.id);
			return {
				...product,
				quantity,
				lineTotal: product.price * quantity,
			};
		});
}

function calculateTotal() {
	return getCartItems().reduce((sum, item) => sum + item.lineTotal, 0);
}

function renderTabs() {
	if (!categoryTabsElement) {
		return;
	}

	const categories = Object.keys(catalogStructure);
	categoryTabsElement.innerHTML = `
		<div class="container py-2">
			<div class="d-flex gap-2 overflow-auto" role="tablist" aria-label="Catégories de produits">
				${categories
					.map(
						(category) => `
							<button
								type="button"
								class="btn ${currentCategory === category ? "btn-primary active" : "btn-outline-secondary"} rounded-pill flex-shrink-0"
								data-category-tab="${category}"
								aria-selected="${currentCategory === category ? "true" : "false"}"
							>
								${category}
							</button>
						`
					)
					.join("")}
			</div>
		</div>
	`;

	categoryTabsElement.querySelectorAll("button[data-category-tab]").forEach((button) => {
		button.addEventListener("click", () => {
			const selectedCategory = button.dataset.categoryTab;
			if (!selectedCategory || selectedCategory === currentCategory) {
				return;
			}

			switchCategory(selectedCategory);
		});
	});
}

function renderProductCard(product) {
	const quantity = getCartQuantity(product.id);
	const actionMarkup =
		quantity === 0
			? `
				<button type="button" class="btn btn-primary w-100" data-action="add" data-product-id="${product.id}">Ajoutez</button>
			`
			: `
				<div class="d-flex align-items-center justify-content-between gap-2 quantity-selector-row">
					<button type="button" class="btn quantity-btn" data-action="decrease" data-product-id="${product.id}">-</button>
					<span class="fw-bold quantity-count">${quantity}</span>
					<button type="button" class="btn quantity-btn" data-action="increase" data-product-id="${product.id}">+</button>
				</div>
			`;

	return `
		<div class="col">
			<article class="product-card h-100 d-flex flex-column bg-white rounded-4 p-3" data-product-id="${product.id}">
				<div class="ratio ratio-1x1 mb-3 overflow-hidden rounded-4">
					<img src="${product.image}" class="product-img w-100 h-100" alt="${product.name}">
				</div>
				<div class="d-flex flex-column flex-grow-1">
					<h3 class="h6 mb-2" style="line-height:1.35; min-height:2.7em; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${product.name}</h3>
					<p class="text-muted small mb-2" style="min-height:2.6em; line-height:1.3;">${product.subcategory}</p>
					<div class="mt-auto">
						<div class="fw-semibold mb-2">${formatPrice(product.price)} €</div>
						${actionMarkup}
					</div>
				</div>
			</article>
		</div>
	`;
}

function getModalActionMarkup(productId) {
	const quantity = getCartQuantity(productId);
	if (quantity === 0) {
		return `<button type="button" class="btn btn-primary w-100" data-action="add" data-product-id="${productId}">Ajoutez au panier</button>`;
	}

	return `
		<div class="d-flex align-items-center justify-content-between gap-2 quantity-selector-row">
			<button type="button" class="btn quantity-btn" data-action="decrease" data-product-id="${productId}">-</button>
			<span class="fw-bold quantity-count">${quantity}</span>
			<button type="button" class="btn quantity-btn" data-action="increase" data-product-id="${productId}">+</button>
		</div>
	`;
}

function openProductModal(productId) {
	const product = getProductById(productId);
	const modalContainer = document.getElementById("modal-product-content");
	if (!product || !modalContainer) {
		return;
	}

	const description = `Une création artisanale de la catégorie ${product.category}, sous-catégorie ${product.subcategory}, préparée avec le savoir-faire de La Talemelerie.`;

	modalContainer.innerHTML = `
		<div class="d-flex justify-content-end p-3 pb-0">
			<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
		</div>
		<div class="ratio ratio-16x9">
			<img src="${product.image}" alt="${product.name}">
		</div>
		<div class="product-modal-body">
			<h3 class="modal-product-title">${product.name}</h3>
			<p class="text-muted small mb-2">${product.subcategory}</p>
			<p class="mb-3">${description}</p>
			<div class="d-flex align-items-center justify-content-between gap-3 mb-3">
				<span class="fw-semibold">Prix</span>
				<span class="fw-bold">${formatPrice(product.price)} €</span>
			</div>
			<div id="modal-product-action">${getModalActionMarkup(product.id)}</div>
		</div>
	`;

	const modalElement = document.getElementById("productModal");
	if (!modalElement) {
		return;
	}

	let modalInstance = bootstrap.Modal.getInstance(modalElement);
	if (!modalInstance) {
		modalInstance = new bootstrap.Modal(modalElement);
	}

	modalElement.addEventListener(
		"hidden.bs.modal",
		() => {
			document.querySelectorAll(".modal-backdrop").forEach((element) => element.remove());
			document.body.classList.remove("modal-open");
			document.body.style.removeProperty("padding-right");
		},
		{ once: true }
	);

	modalInstance.show();
}

const scrollTopButton = document.getElementById("scroll-top-btn");
if (scrollTopButton) {
	window.addEventListener("scroll", () => {
		if (window.scrollY > 300) {
			scrollTopButton.classList.remove("d-none");
		} else {
			scrollTopButton.classList.add("d-none");
		}
	});

	scrollTopButton.addEventListener("click", () => {
		window.scrollTo({ top: 0, behavior: "smooth" });
	});
}

function renderProducts() {
	if (!catalogElement) {
		return;
	}

	const currentProducts = products.filter((product) => product.category === currentCategory);
	const groupedBySubcategory = currentProducts.reduce((acc, product) => {
		if (!acc[product.subcategory]) {
			acc[product.subcategory] = [];
		}
		acc[product.subcategory].push(product);
		return acc;
	}, {});

	const sectionsMarkup = Object.entries(groupedBySubcategory)
		.map(
			([subcategory, subcategoryProducts]) => `
				<section class="mb-4" data-subcategory="${subcategory}">
					<h3 class="h6 fw-semibold mb-3">${subcategory}</h3>
					<div class="row row-cols-2 g-3">
						${subcategoryProducts.map((product) => renderProductCard(product)).join("")}
					</div>
				</section>
			`
		)
		.join("");

	catalogElement.innerHTML = `<div class="catalog-sections">${sectionsMarkup}</div>`;
}

function switchCategory(nextCategory) {
	if (!catalogElement || nextCategory === currentCategory) {
		return;
	}

	const currentHeight = catalogElement.offsetHeight;
	catalogElement.style.minHeight = `${currentHeight}px`;
	catalogElement.style.opacity = "0";
	catalogElement.style.transition = "opacity 180ms ease";

	window.requestAnimationFrame(() => {
		currentCategory = nextCategory;
		renderTabs();
		catalogElement.innerHTML = "";
		renderProducts();
		catalogElement.style.opacity = "1";
		window.setTimeout(() => {
			catalogElement.style.minHeight = "";
		}, 220);
	});
}

function updateTotalDisplay() {
	if (totalAmountElement) {
		totalAmountElement.textContent = formatPrice(calculateTotal());
	}
}

function validatePhone(phoneValue) {
	const sanitizedValue = phoneValue.replace(/[\s\-().]/g, "");
	return /^\+?[0-9]{8,15}$/.test(sanitizedValue);
}

function updateFieldState(inputElement, isValid) {
	if (!inputElement) {
		return;
	}

	inputElement.classList.toggle("is-valid", isValid);
	inputElement.classList.toggle("is-invalid", !isValid);
}

// Replace the existing validateForm function with this updated version
function validateForm() {
	const nameValue = clientNameInput.value.trim();
	const isNameValid = nameValue.length > 0 && /^[a-zA-ZÀ-ÿ\s-]+$/.test(nameValue);
	const isPhoneValid = validatePhone(phoneNumberInput.value.trim());
	const pickupValue = pickupDatetimeInput.value.trim();
	let isPickupDatetimeValid = false;

	if (pickupValue.length > 0) {
		const selectedDate = new Date(pickupValue);
		if (!Number.isNaN(selectedDate.getTime())) {
			const minAllowedDate = new Date(Date.now() + 30 * 60 * 1000);
			const isFuture = selectedDate >= minAllowedDate;
			const is15MinStep = selectedDate.getMinutes() % 15 === 0; // Strict 15-min interval check
			isPickupDatetimeValid = isFuture && is15MinStep;
		}
	}

	const isAllergenAccepted = allergenCheckbox.checked;
	const hasItems = calculateTotal() > 0;

	updateFieldState(clientNameInput, isNameValid);
	updateFieldState(phoneNumberInput, isPhoneValid);
	updateFieldState(pickupDatetimeInput, isPickupDatetimeValid);
	allergenCheckbox.classList.toggle("is-valid", isAllergenAccepted);
	allergenCheckbox.classList.toggle("is-invalid", !isAllergenAccepted);

	const isFormValid = isNameValid && isPhoneValid && isPickupDatetimeValid && isAllergenAccepted && hasItems;

	confirmOrderButton.disabled = !hasItems;

	return isFormValid;
}

function changeQuantity(productId, delta) {
	const currentQuantity = getCartQuantity(productId);
	const nextQuantity = Math.max(0, currentQuantity + delta);

	if (nextQuantity === 0) {
		delete cart[productId];
	} else {
		cart[productId] = nextQuantity;
	}

	renderProducts();
	updateTotalDisplay();
	validateForm();
}

function buildPayload() {
	const items = getCartItems().map((item) => ({
		name: item.name,
		quantity: item.quantity,
		line_total: Number(item.lineTotal.toFixed(2)),
	}));

	return {
		customer_name: clientNameInput.value.trim(),
		customer_phone: phoneNumberInput.value.trim(),
		pickup_datetime: pickupDatetimeInput.value,
		items,
		total_price: Number(calculateTotal().toFixed(2)),
	};
}

if (catalogElement) {
	catalogElement.addEventListener("click", (event) => {
		const interactiveControl = event.target.closest("button[data-action], .quantity-count");
		if (!interactiveControl) {
			const productCard = event.target.closest(".product-card[data-product-id]");
			if (productCard) {
				const productId = Number(productCard.dataset.productId);
				if (!Number.isNaN(productId)) {
					openProductModal(productId);
				}
				return;
			}
		}

		const button = event.target.closest("button[data-action][data-product-id]");
		if (!button) {
			return;
		}

		const productId = Number(button.dataset.productId);
		const action = button.dataset.action;

		if (action === "add") {
			cart[productId] = 1;
			renderProducts();
			updateTotalDisplay();
			validateForm();
			return;
		}

		if (action === "increase") {
			changeQuantity(productId, 1);
			return;
		}

		if (action === "decrease") {
			changeQuantity(productId, -1);
		}
	});
}

const modalProductContent = document.getElementById("modal-product-content");
if (modalProductContent) {
	modalProductContent.addEventListener("click", (event) => {
		const button = event.target.closest("button[data-action][data-product-id]");
		if (!button) {
			return;
		}

		const productId = Number(button.dataset.productId);
		const action = button.dataset.action;

		if (action === "add") {
			cart[productId] = 1;
		} else if (action === "increase") {
			cart[productId] = getCartQuantity(productId) + 1;
		} else if (action === "decrease") {
			const nextQuantity = Math.max(0, getCartQuantity(productId) - 1);
			if (nextQuantity === 0) {
				delete cart[productId];
			} else {
				cart[productId] = nextQuantity;
			}
		}

		renderProducts();
		updateTotalDisplay();
		validateForm();
		openProductModal(productId);
	});
}

// ЖЕСТКАЯ КОРРЕКЦИЯ ВРЕМЕНИ (Принудительный шаг 15 минут)
pickupDatetimeInput.addEventListener("change", (e) => {
	if (!e.target.value) return;

	const selectedDate = new Date(e.target.value);
	if (Number.isNaN(selectedDate.getTime())) return;

	const minutes = selectedDate.getMinutes();
	const remainder = minutes % 15;

	// Если время уже кратно 15, ничего не делаем
	if (remainder === 0) return;

	// Округляем до ближайшего 15-минутного интервала
	if (remainder >= 8) {
		selectedDate.setMinutes(minutes + (15 - remainder));
	} else {
		selectedDate.setMinutes(minutes - remainder);
	}
	selectedDate.setSeconds(0, 0);

	// Конвертируем обратно в локальное время для инпута (сдвиг часового пояса)
	const offset = selectedDate.getTimezoneOffset() * 60000;
	const localDate = new Date(selectedDate.getTime() - offset);

	// Перезаписываем значение в инпуте и дергаем валидацию
	e.target.value = localDate.toISOString().slice(0, 16);
	validateForm();
});

clientNameInput.addEventListener("input", validateForm);
phoneNumberInput.addEventListener("input", validateForm);
pickupDatetimeInput.addEventListener("change", validateForm);
pickupDatetimeInput.addEventListener("input", validateForm);
allergenCheckbox.addEventListener("change", validateForm);

if (confirmOrderButton) {
	confirmOrderButton.addEventListener("click", () => {
		if (orderFormSection) {
			const rect = orderFormSection.getBoundingClientRect();
			// ACTION 1: If the form is below 40% of the viewport height, we are in the catalog. Scroll down.
			if (rect.top > window.innerHeight * 0.4) {
				orderFormSection.scrollIntoView({ behavior: "smooth", block: "start" });
				return;
			}
		}

		// ACTION 2: We are at the form. Trigger rigorous validation.
		if (!checkoutForm) {
			return;
		}

		checkoutForm.classList.add("was-validated");

		if (!validateForm()) {
			return; // Validation failed, the UI will show the red borders
		}

		// Validation passed, submit order
		const orderData = buildPayload();

		if (window.Telegram && window.Telegram.WebApp) {
			const tg = window.Telegram.WebApp;
			tg.sendData(JSON.stringify(orderData));
			tg.close(); // Close Web App after sending data
		} else {
			alert("Ошибка: Web App запущен вне Telegram!");
		}
	});
}

renderTabs();
renderProducts();
updateTotalDisplay();
validateForm();
