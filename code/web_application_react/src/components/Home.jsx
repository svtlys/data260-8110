import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useSelector, useDispatch } from "react-redux";
import { fetchListings, deleteListing } from "../store/listingsSlice";

function Home({ isLoggedIn }) {
  const dispatch = useDispatch();
  const { items: listings, status, error } = useSelector((state) => state.listings);

  useEffect(() => {
    if (isLoggedIn) {
      dispatch(fetchListings());
    }
  }, [isLoggedIn, dispatch]);

  const handleDelete = (id) => {
    dispatch(deleteListing(id));
  };

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

      {status === "loading" && <div className="alert alert-info">Loading listings...</div>}
      {status === "failed" && <div className="alert alert-danger">{error}</div>}

      {status === "succeeded" && listings.length === 0 && (
        <div className="alert alert-secondary">No listings yet — add one!</div>
      )}

      {status === "succeeded" && listings.length > 0 && (
        <table className="table table-striped">
          <thead>
            <tr>
              <th>ID</th>
              <th>Address</th>
              <th>Listing Code</th>
              <th>Available Units</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {listings.map((listing) => (
              <tr key={listing.id}>
                <td>{listing.id}</td>
                <td>{listing.address}</td>
                <td>{listing.listing_code || "—"}</td>
                <td>{listing.available_units}</td>
                <td>
                  <Link
                    to={`/update?id=${listing.id}`}
                    className="btn btn-sm btn-outline-primary me-2"
                  >
                    Update
                  </Link>
                  <button
                    onClick={() => handleDelete(listing.id)}
                    className="btn btn-sm btn-outline-danger"
                  >
                    Delete
                  </button>
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