import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import axios from "axios";

const API_BASE = "http://localhost:8010/api";


const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});


export const fetchListings = createAsyncThunk(
  "listings/fetchListings",
  async (_, { rejectWithValue }) => {
    try {
      const response = await api.get("/listings?page=1&page_size=50");
      return response.data;
    } catch (err) {
      return rejectWithValue(err.response?.data?.detail || "Failed to fetch listings");
    }
  }
);

export const createListing = createAsyncThunk(
  "listings/createListing",
  async (newListing, { rejectWithValue }) => {
    try {
      const response = await api.post("/listings", newListing);
      return response.data;
    } catch (err) {
      return rejectWithValue(err.response?.data?.detail || "Failed to create listing");
    }
  }
);

export const updateListing = createAsyncThunk(
  "listings/updateListing",
  async ({ id, ...updates }, { rejectWithValue }) => {
    try {
      const response = await api.put(`/listings/${id}`, updates);
      return response.data;
    } catch (err) {
      return rejectWithValue(err.response?.data?.detail || "Failed to update listing");
    }
  }
);

export const deleteListing = createAsyncThunk(
  "listings/deleteListing",
  async (id, { rejectWithValue }) => {
    try {
      await api.delete(`/listings/${id}`);
      return id;
    } catch (err) {
      return rejectWithValue(err.response?.data?.detail || "Failed to delete listing");
    }
  }
);



const listingsSlice = createSlice({
  name: "listings",
  initialState: {
    items: [],
    status: "idle", // idle | loading | succeeded | failed
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      // fetch
      .addCase(fetchListings.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(fetchListings.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.items = action.payload;
      })
      .addCase(fetchListings.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.payload;
      })
      // create
      .addCase(createListing.fulfilled, (state, action) => {
        state.items.push(action.payload);
      })
      .addCase(createListing.rejected, (state, action) => {
        state.error = action.payload;
      })
      // update
      .addCase(updateListing.fulfilled, (state, action) => {
        const index = state.items.findIndex((item) => item.id === action.payload.id);
        if (index !== -1) {
          state.items[index] = action.payload;
        }
      })
      .addCase(updateListing.rejected, (state, action) => {
        state.error = action.payload;
      })
      // delete
      .addCase(deleteListing.fulfilled, (state, action) => {
        state.items = state.items.filter((item) => item.id !== action.payload);
      })
      .addCase(deleteListing.rejected, (state, action) => {
        state.error = action.payload;
      });
  },
});

export default listingsSlice.reducer;