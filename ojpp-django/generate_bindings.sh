rm -rf generated/

# NeTEx
xsdata generate \
       --package generated \
       --structure-style namespace-clusters \
       ./NeTEx/xsd

echo > generated/uk/org/netex/netex/__init__.py

# SIRI
xsdata generate \
       --package generated.siri \
       --structure-style single-package \
       ./SIRI/xsd/siri_vehicleMonitoring_service.xsd
