const API_BASE = 'http://localhost:8010';

const trackSubmission = (() => {
  let count = 0;
  return () => {
    count += 1;
    console.log(`Submission #${count}`);
    return count;
  };
})();
 
 
const validateForm = (descriptionValue, termsChecked) => {
  if (descriptionValue.length <= 25) {
    alert("Description must be more than 25 characters long.");
    return false;
  }
  if (!termsChecked) {
    alert("You must agree to the terms and conditions.");
    return false;
  }
  return true;
};
 

function showState(state) {
  document.getElementById("loadingState").style.display = state === "loading" ? "block" : "none";
  document.getElementById("emptyState").style.display = state === "empty" ? "block" : "none";
  document.getElementById("errorState").style.display = state === "error" ? "block" : "none";
}
 
function renderListings(listings) {
  const list = document.getElementById("listingsList");
  list.innerHTML = "";
  listings.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.address ?? "(no address)"} — ${item.landlordName ?? "(no landlord)"}`;
    list.appendChild(li);
  });
}


async function loadListings(searchTerm = '') {
  showState("loading");
  document.getElementById("listingsList").innerHTML = "";
 
  try {
    const url = searchTerm
      ? `${API_BASE}/listings?search=${encodeURIComponent(searchTerm)}`
      : `${API_BASE}/listings`;
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status}`);
    }
    const listings = await response.json();
 
    if (listings.length === 0) {
      showState("empty");
    } else {
      showState(null);
      renderListings(listings);
    }
  } catch (error) {
    console.error("Failed to load listings:", error);
    showState("error");
  }
}
 
document.getElementById("listingForm").addEventListener("submit", (event) => {
  event.preventDefault();
 
  const form = event.target;
  const description = form.description.value;
  const termsChecked = form.terms.checked;
 
  const isValid = validateForm(description, termsChecked);
  if (!isValid) {
    return;
  }
 
  const formDataObj = {
    address: form.address.value,
    landlordName: form.landlordName.value,
    submitterEmail: form.submitterEmail.value,
    description: form.description.value,
    category: form.category.value,
  };
 
  const jsonString = JSON.stringify(formDataObj);
  console.log("JSON string:", jsonString);
 
  const parsedObj = JSON.parse(jsonString);
  const { address, submitterEmail } = parsedObj;
  console.log("Primary field (address):", address);
  console.log("Email field:", submitterEmail);
 
  const updatedObj = {
    ...parsedObj,
    submissionDate: new Date().toISOString(),
  };
    console.log("Updated object with submissionDate:", updatedObj);

  trackSubmission();

  const body = new URLSearchParams();
  body.append("address", form.address.value);
  body.append("landlordName", form.landlordName.value);

  fetch(`${API_BASE}/listings`, {
    method: "POST",
    body: body,
  })
    .then((res) => res.json())
    .then((data) => {
      console.log("Created record:", data);
      form.reset();
      loadListings(); // redirecting to "home view" = refresh the list
    })
    .catch((err) => {
      console.error("Failed to create listing:", err);
      showState("error");
    });
});
 
document.getElementById("updateBtn").addEventListener("click", () => {
  const body = new URLSearchParams();
  body.append("address", "456 Updated Ave, San Jose, CA");
  body.append("landlordName", "Updated Property Group");

  fetch(`${API_BASE}/listings/1`, {
    method: "PUT",
    body: body,
  })
    .then((res) => res.json())
    .then((data) => {
      console.log("Updated record:", data);
      loadListings();
    })
    .catch((err) => {
      console.error("Failed to update listing:", err);
      showState("error");
    });
});

document.getElementById("deleteBtn").addEventListener("click", () => {
  fetch(`${API_BASE}/listings/highest`, {
    method: "DELETE",
  })
    .then((res) => res.json())
    .then((data) => {
      console.log("Deleted record:", data);
      loadListings();
    })
    .catch((err) => {
      console.error("Failed to delete listing:", err);
      showState("error");
    });
});

document.getElementById("searchInput").addEventListener("input", (event) => {
  loadListings(event.target.value);
});

loadListings();