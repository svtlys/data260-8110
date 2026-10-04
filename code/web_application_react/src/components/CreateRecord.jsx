import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { createListing } from "../store/listingsSlice";

function CreateRecord({ isLoggedIn }) {
  const [address, setAddress] = useState("");
  const [landlordId, setLandlordId] = useState("");
  const [listingCode, setListingCode] = useState("");
  const [availableUnits, setAvailableUnits] = useState(1);
  const [error, setError] = useState(null);

  const dispatch = useDispatch();
  const navigate = useNavigate();

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    const payload = {
      address,
      landlord_id: landlordId ? parseInt(landlordId, 10) : null,
      listing_code: listingCode || null,
      available_units: availableUnits,
    };

    const result = await dispatch(createListing(payload));

    if (createListing.fulfilled.match(result)) {
      navigate("/");
    } else {
      setError(result.payload || "Failed to create listing.");
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-warning">Login required.</div>
      </div>
    );
  }

  return (
    <div className="container mt-5" style={{ maxWidth: "480px" }}>
      <div className="card shadow-sm">
        <div className="card-body">
          <h2 className="mb-4 text-dark">Add Rental Listing</h2>

          {error && <div className="alert alert-danger">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="mb-3">
              <label htmlFor="address" className="form-label">Property Address</label>
              <input
                type="text"
                className="form-control"
                id="address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="e.g. 123 Main St, San Jose, CA"
                required
                autoFocus
              />
            </div>

            <div className="mb-3">
              <label htmlFor="landlordId" className="form-label">Landlord ID (optional)</label>
              <input
                type="number"
                className="form-control"
                id="landlordId"
                value={landlordId}
                onChange={(e) => setLandlordId(e.target.value)}
                placeholder="e.g. 1"
              />
            </div>

            <div className="mb-3">
              <label htmlFor="listingCode" className="form-label">Listing Code (optional, format XX-NNNN)</label>
              <input
                type="text"
                className="form-control"
                id="listingCode"
                value={listingCode}
                onChange={(e) => setListingCode(e.target.value)}
                placeholder="e.g. SJ-10234"
              />
            </div>

            <div className="mb-3">
              <label htmlFor="availableUnits" className="form-label">Available Units</label>
              <input
                type="number"
                className="form-control"
                id="availableUnits"
                value={availableUnits}
                onChange={(e) => setAvailableUnits(parseInt(e.target.value, 10) || 1)}
                min="0"
                required
              />
            </div>

            <button type="submit" className="btn btn-primary w-100">
              Add Listing
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default CreateRecord;