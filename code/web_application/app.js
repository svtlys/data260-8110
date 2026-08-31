// Closure to track successful submission count
const trackSubmission = (() => {
  let count = 0;
  return () => {
    count += 1;
    console.log(`Submission #${count}`);
    return count;
  };
})();

// Arrow-function validator
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

  form.reset();
});
