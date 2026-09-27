import { useState, useEffect } from "react";
import { Link } from "react-router-dom";

const API_BASE = "http://localhost:8010";

function Home({ isLoggedIn }) {
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isLoggedIn) {
      setLoading(false);
      return;
    }

    async function fetchListings() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/api/listings`, {
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error(`Server responded with ${response.status}`);
        }
        const data = await response.json();
        setListings(data);
      } catch (err) {
        console.error("Failed to load listings:", err);
        setError("Failed to load listings. Please try again.");
      } finally {
        setLoading(false);
      }
    }

    fetchListings();
  }, [isLoggedIn]);

  if (!isLoggedIn) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-warning">Login required.</div>
        <Link to="/login" className="btn btn-primary">Go to Login</Link>
      </div>
    );
  }

  return (
    <div className="container mt-5">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h1>Rental Housing Listings</h1>
        <Link to="/create" className="btn btn-primary">Add Record</Link>
      </div>

      {loading && <div className="alert alert-info">Loading listings...</div>}
      {error && <div className="alert alert-danger">{error}</div>}

      {!loading && !error && listings.length === 0 && (
        <div className="alert alert-secondary">No listings yet — add one!</div>
      )}

      {!loading && !error && listings.length > 0 && (
        <table className="table table-striped">
          <thead>
            <tr>
              <th>ID</th>
              <th>Address</th>
              <th>Landlord</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {listings.map((listing) => (
              <tr key={listing.id}>
                <td>{listing.id}</td>
                <td>{listing.address}</td>
                <td>{listing.landlordName}</td>
                <td>
                  <Link
                    to={`/update?id=${listing.id}`}
                    className="btn btn-sm btn-outline-primary me-2"
                  >
                    Update
                  </Link>
                  <Link
                    to={`/delete?id=${listing.id}`}
                    className="btn btn-sm btn-outline-danger"
                  >
                    Delete
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default Home;