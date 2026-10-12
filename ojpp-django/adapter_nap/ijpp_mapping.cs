/*
    This is the reference code to convert between NAP-NeTEx and internal IJPP IDs.
    It is kept here for reference and for testing our implementation in "ijpp_mapping.py".
    THE REPOSITORY-LEVEL LICENSE DOES NOT APPLY TO THIS CODE
*/

private string getIdFromGuid(string netexTypeName, Guid id, string epipFrameName = null) {
    return $"{Country}:{Region}:{netexTypeName}:{epipFrameName}{(String.IsNullOrWhiteSpace(epipFrameName) ? "" : "_")}{id}:{ExternalSystemName}";
}
private string getIdFromGuid < NeTExType > (Guid id, string epipFrameName = null) {
    return getIdFromGuid(typeof(NeTExType).Name, id, epipFrameName);
}
private string getIdFromIJPP(Type IJPPType, string netexTypeName, int id, int id1 = 0, int id2 = 0) {
    var guid = new Guid(
        (uint) id2,
        ijppId_B,
        ijppId_C[IJPPType],
        (byte)((id1 >> 24) & 0xff),
        (byte)((id1 >> 16) & 0xff),
        (byte)((id1 >> 8) & 0xff),
        (byte)(id1 & 0xff),
        (byte)((id >> 24) & 0xff),
        (byte)((id >> 16) & 0xff),
        (byte)((id >> 8) & 0xff),
        (byte)(id & 0xff)
    );
    return getIdFromGuid(netexTypeName, guid, null);
}
private string getIdFromIJPP < IJPPType, NeTExType > (int id, int id1 = 0, int id2 = 0) {
    return getIdFromIJPP(typeof(IJPPType), typeof(NeTExType).Name, id, id1, id2);
}